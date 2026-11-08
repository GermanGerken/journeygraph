"""Unit tests for advisory inspection and draft mapping rendering."""

from __future__ import annotations

import json

import pytest

from journeygraph.domain.models import SourceRecord
from journeygraph.ingestion.inspection import (
    MAX_SHOWN_VALUES,
    _candidates,
    inspect_records,
    render_draft,
    render_path,
    render_report,
)
from journeygraph.ingestion.mapping import parse_mapping


def _records(*rows: dict[str, object]) -> list[SourceRecord]:
    return [SourceRecord(row, f"line {index + 1}", index) for index, row in enumerate(rows)]


def _row(index: int, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "trace_id": f"t{index % 2}",
        "span_id": f"s{index}",
        "timestamp": f"2026-09-21T10:00:0{index}Z",
        "duration_ms": index,
        "operation": "tool",
        "tool_name": "search",
        "status": "ok",
    }
    row.update(extra)
    return row


def _profile(inspection: object, path: str) -> object:
    return next(item for item in inspection.profiles if item.path == path)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("segments", "expected"),
    [
        (("a", "b"), "a.b"),
        (("attributes", "tool.name"), 'attributes."tool.name"'),
        (("",), '""'),
        (('say "hi"',), None),
    ],
)
def test_render_path_quotes_dotted_and_empty_segments(
    segments: tuple[str, ...], expected: str | None
) -> None:
    assert render_path(segments) == expected
    if expected is not None:
        mapping = parse_mapping(
            f'mapping_version = "1"\n[fields]\ntrace_id = {json.dumps(expected)}\n'
            'step_id = "s"\ntimestamp = "t"\noperation_type = "o"\ncomponent = "c"\n'
            'duration_ms = "d"\nstatus = "x"\n'
        )
        assert mapping.fields["trace_id"].segments == segments


@pytest.mark.parametrize(
    ("value", "hint"),
    [
        (100_000_000, "epoch_s"),
        (99_999_999_999, "epoch_s"),
        (100_000_000_000, "epoch_ms"),
        ("1790000000000000", "epoch_us"),
        (1_790_000_000_000_000_000, "epoch_ns"),
        (1.79e9, "epoch_s"),
    ],
)
def test_epoch_units_follow_the_documented_magnitude_ranges(value: object, hint: str) -> None:
    inspection = inspect_records(_records({"started": value}))
    assert hint in _profile(inspection, "started").hints  # type: ignore[attr-defined]


@pytest.mark.parametrize("values", [[99_999_999], [10**20], [1_790_000_000, 1_790_000_000_000]])
def test_values_outside_one_epoch_range_get_no_epoch_hint(values: list[int]) -> None:
    inspection = inspect_records(_records(*({"started": value} for value in values)))
    hints = _profile(inspection, "started").hints  # type: ignore[attr-defined]
    assert hints == ("numeric",)


def test_profiles_count_presence_nulls_types_and_buckets() -> None:
    # Arrange
    rows = [{"a": index, "b": None if index % 2 else "x", "c": {}, "d": [1]} for index in range(12)]

    # Act
    inspection = inspect_records(_records(*rows))

    # Assert
    a, b, c, d = (_profile(inspection, path) for path in ("a", "b", "c", "d"))
    assert (a.present, a.nulls, a.types, a.distinct) == (12, 0, ("integer",), "11-100")  # type: ignore[attr-defined]
    assert (b.present, b.nulls, b.types, b.distinct) == (12, 6, ("string",), "1")  # type: ignore[attr-defined]
    assert c.hints == ("empty_object",)  # type: ignore[attr-defined]
    assert d.types == ("array",)  # type: ignore[attr-defined]
    many = inspect_records(_records(*({"a": index} for index in range(150))))
    assert _profile(many, "a").distinct == ">100"  # type: ignore[attr-defined]
    nulls = inspect_records(_records({"a": None}))
    assert _profile(nulls, "a").types == ("null",)  # type: ignore[attr-defined]
    assert _profile(nulls, "a").distinct == "0"  # type: ignore[attr-defined]


def test_hints_distinguish_identifiers_timestamps_and_free_text() -> None:
    inspection = inspect_records(
        _records(
            {"id": "abc-1", "at": "2026-09-21T10:00:00.5+02:00", "text": "two words", "flag": True},
        )
    )
    assert _profile(inspection, "id").hints == ("identifier",)  # type: ignore[attr-defined]
    assert _profile(inspection, "at").hints == ("rfc3339",)  # type: ignore[attr-defined]
    assert _profile(inspection, "text").hints == ()  # type: ignore[attr-defined]
    assert _profile(inspection, "flag").types == ("boolean",)  # type: ignore[attr-defined]
    mixed = inspect_records(_records({"id": "abc"}, {"id": 5}))
    assert "identifier" not in _profile(mixed, "id").hints  # type: ignore[attr-defined]


def test_suggestions_cover_canonical_fields_from_names_and_shapes() -> None:
    # Arrange
    rows = [
        _row(
            index,
            parent_span_id=None if index == 0 else f"s{index - 1}",
            result="success",
            usage={"input_tokens": 3, "output_tokens": 4, "cost_usd": 0.5},
            service="api",
            user_name="someone",
        )
        for index in range(3)
    ]

    # Act
    inspection = inspect_records(_records(*rows))

    # Assert
    paths = {name: suggestion.path for name, suggestion in inspection.fields.items()}
    assert paths == {
        "trace_id": "trace_id",
        "step_id": "span_id",
        "parent_step_id": "parent_span_id",
        "timestamp": "timestamp",
        "operation_type": "operation",
        "component": "tool_name",
        "status": "status",
        "outcome": "result",
        "input_tokens": "usage.input_tokens",
        "output_tokens": "usage.output_tokens",
        "cost_usd": "usage.cost_usd",
    }
    assert inspection.duration == {"field": "duration_ms", "unit": "ms"}
    assert inspection.timestamp_unit == "iso8601"
    assert {key: item.path for key, item in inspection.metadata.items()} == {"service": "service"}
    parse_mapping(render_draft(inspection))


@pytest.mark.parametrize(
    ("name", "unit"), [("latency_s", "s"), ("elapsed_ns", "ns"), ("duration", "ms")]
)
def test_single_duration_units_come_from_name_suffixes(name: str, unit: str) -> None:
    rows = [
        {**{k: v for k, v in _row(index).items() if k != "duration_ms"}, name: 5}
        for index in range(2)
    ]
    inspection = inspect_records(_records(*rows))
    assert inspection.duration == {"field": name, "unit": unit}


def test_start_and_end_pairs_need_the_same_unit() -> None:
    same = [{"session_id": "a", "start_ms": 1_790_000_000_000, "end_ms": 1_790_000_000_005}]
    mixed = [{"session_id": "a", "start_ms": 1_790_000_000_000, "end_ms": 1_790_000_000}]
    assert inspect_records(_records(*same)).duration == {"start": "start_ms", "end": "end_ms"}
    assert inspect_records(_records(*same)).timestamp_unit == "unix_ms"
    assert inspect_records(_records(*mixed)).duration == {}


def test_ties_prefer_the_shortest_then_lexically_first_path() -> None:
    inspection = inspect_records(
        _records({"session_id": "a", "thread_id": "b", "meta": {"run_id": "c"}})
    )
    assert inspection.fields["trace_id"].path == "session_id"


def test_unaddressable_paths_are_reported_but_never_suggested() -> None:
    inspection = inspect_records(_records({'trace "id"': "a"}))
    assert "trace_id" not in inspection.fields
    assert "(unaddressable: key contains a quote)" in render_report(inspection)


def test_tokens_are_kept_only_with_show_values_and_only_when_short_and_few() -> None:
    rows = [_row(index, status=["OK", "STATUS_ERROR", "Unset"][index % 3]) for index in range(6)]
    hidden = inspect_records(_records(*rows))
    shown = inspect_records(_records(*rows), show_values=True)
    assert _profile(hidden, "status").tokens is None  # type: ignore[attr-defined]
    assert _profile(shown, "status").tokens == ("OK", "STATUS_ERROR", "Unset")  # type: ignore[attr-defined]
    draft = render_draft(shown)
    assert '"OK" = "ok"' in draft
    assert '"STATUS_ERROR" = "error"' in draft
    assert '"Unset" = "unset"' in draft
    assert "observed status tokens: OK, STATUS_ERROR, Unset" in render_report(shown)
    free_text = inspect_records(_records(_row(0, status="not a token")), show_values=True)
    assert _profile(free_text, "status").tokens is None  # type: ignore[attr-defined]
    many = [_row(index, status=f"S{index}") for index in range(MAX_SHOWN_VALUES + 1)]
    crowded = inspect_records(_records(*many), show_values=True)
    assert _profile(crowded, "status").tokens is None  # type: ignore[attr-defined]


def test_value_maps_for_outcomes_and_operation_types() -> None:
    rows = [
        _row(
            index,
            result=["success", "Failed", "maybe"][index % 3],
            operation=["LLM", "tool", "Thing"][index % 3],
        )
        for index in range(3)
    ]
    draft = render_draft(inspect_records(_records(*rows), show_values=True))
    assert '"Failed" = "failure"' in draft
    assert '# "maybe" = ""  # TODO' in draft
    assert '"LLM" = "llm"' in draft
    assert '"tool"' not in draft.split("[values.operation_type]")[1].split("\n\n")[0]
    assert '# "Thing" = ""  # TODO' in draft


def test_incomplete_drafts_keep_required_todos_and_report_them() -> None:
    inspection = inspect_records(_records({"x": 1}))
    draft = render_draft(inspection)
    for name in ("trace_id", "step_id", "timestamp", "operation_type", "component", "status"):
        assert f'# {name} = ""  # TODO: required' in draft
    assert '# duration_ms = ""  # TODO: required' in draft
    report = render_report(inspection)
    assert report.endswith(
        "missing required fields: trace_id, step_id, timestamp, operation_type, component, "
        "status, duration_ms\n"
    )


def test_sample_limits_records_and_must_be_positive() -> None:
    rows = _records(*(_row(index) for index in range(5)))
    assert inspect_records(rows, sample=2).sampled == 2
    assert inspect_records(rows, sample=2).total == 5
    for bad in (0, -1, True):
        with pytest.raises(ValueError, match="positive integer"):
            inspect_records(rows, sample=bad)  # type: ignore[arg-type]


def _scores(name: str, *values: object) -> dict[str, int]:
    inspection = inspect_records(_records(*({name: value} for value in values)))
    return _candidates(_profile(inspection, name))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "values", "expected"),
    [
        ("trace_id", ("a", "b"), {"trace_id": 4}),
        ("sessionKey", ("a", "b"), {"trace_id": 3}),
        ("span_id", ("a", "b"), {"step_id": 4}),
        ("id", ("a", "b"), {"step_id": 4}),
        ("event_key", ("a",), {"step_id": 3}),
        ("parent_span_id", ("a",), {"parent_step_id": 4}),
        ("trace_id", (1.5,), {}),
        ("started_at", ("2026-09-21T10:00:00Z",), {"timestamp": 4}),
        ("created_at", ("2026-09-21T10:00:00Z",), {"timestamp": 3}),
        ("event_time", (1_790_000_000,), {"timestamp": 3}),
        ("ended_at", ("2026-09-21T10:00:00Z",), {"end": 3}),
        ("started_at", ("yesterday",), {}),
        ("latency", (5,), {"duration": 3}),
        ("price", ("0.5",), {"cost_usd": 3}),
        ("input_tokens", (3,), {"input_tokens": 3}),
        ("completion_token", (3,), {"output_tokens": 3}),
        ("tokens", (3,), {}),
        ("span_kind", ("llm",), {"operation_type": 3}),
        ("state", ("ok",), {"status": 3}),
        ("status", (1, 2), {"status": 3}),
        ("status_id", ("a",), {}),
        ("verdict", ("pass",), {"outcome": 3}),
        ("function", ("search",), {"component": 3}),
        ("tool_name", ("search",), {"component": 4}),
        ("agent_name", ("planner",), {"component": 2}),
        ("first_name", ("Ann",), {}),
        ("status", tuple(f"s{index}" for index in range(150)), {}),
    ],
)
def test_candidate_scores_are_exact(
    name: str, values: tuple[object, ...], expected: dict[str, int]
) -> None:
    assert _scores(name, *values) == expected


@pytest.mark.parametrize(
    ("count", "bucket"),
    [(1, "1"), (2, "2-10"), (10, "2-10"), (11, "11-100"), (100, "11-100"), (101, ">100")],
)
def test_distinct_buckets_have_exact_edges(count: int, bucket: str) -> None:
    inspection = inspect_records(_records(*({"a": index} for index in range(count))))
    assert _profile(inspection, "a").distinct == bucket  # type: ignore[attr-defined]


def test_report_layout_is_exact() -> None:
    inspection = inspect_records(_records({"session_id": "a", "note": "free text"}))
    assert render_report(inspection) == (
        "inspected: 1 of 1 record(s); 2 source path(s)\n"
        "path        present  null  types   hints       distinct  suggestion\n"
        "note        1        0     string  -           1         -\n"
        "session_id  1        0     string  identifier  1         trace_id\n"
        "missing required fields: step_id, timestamp, operation_type, component, status, "
        "duration_ms\n"
    )


def test_draft_layout_is_exact_for_a_complete_sample() -> None:
    rows = [
        {
            "session_id": "a",
            "span_id": f"s{index}",
            "start_ms": 1_790_000_000_000 + index,
            "end_ms": 1_790_000_000_005 + index,
            "kind": "LLM",
            "tool_name": "search",
            "status": "OK",
            "env": "prod",
        }
        for index in range(2)
    ]
    draft = render_draft(inspect_records(_records(*rows), show_values=True))
    assert draft == (
        "# Draft field mapping generated by `journeygraph inspect` from 2 sampled record(s).\n"
        "# Every entry is a heuristic suggestion: review each line before using this file.\n"
        'mapping_version = "1"\n'
        "\n"
        "[fields]\n"
        'trace_id = "session_id"  # name+shape\n'
        'step_id = "span_id"  # name+shape\n'
        'timestamp = "start_ms"  # name+shape\n'
        'operation_type = "kind"  # name+shape\n'
        'component = "tool_name"  # name+shape\n'
        'status = "status"  # name+shape\n'
        "\n"
        "[timestamp]\n"
        'unit = "unix_ms"\n'
        "\n"
        "[duration]\n"
        'start = "start_ms"\n'
        'end = "end_ms"\n'
        "\n"
        "[values.status]\n"
        '"OK" = "ok"\n'
        "\n"
        "[values.operation_type]\n"
        '"LLM" = "llm"\n'
        "\n"
        "[metadata]\n"
        'environment = "env"  # allowlisted name\n'
    )
    parse_mapping(draft)


def test_draft_without_values_explains_how_to_add_value_maps() -> None:
    rows = [_row(index, result="success") for index in range(2)]
    draft = render_draft(inspect_records(_records(*rows)))
    for target in ("status", "outcome", "operation_type"):
        assert (
            f"# [values.{target}]  # map source values to canonical {target} values if needed;\n"
            "# rerun with --show-values to list short observed tokens.\n"
        ) in draft


def test_metadata_suggestions_skip_used_objects_and_duplicates() -> None:
    inspection = inspect_records(
        _records(
            {
                "service": "a",
                "deep": {"service": "b"},
                "region": {"x": 1},
                "version": 2,
                "model": ["x"],
                "workflow": None,
            }
        )
    )
    assert {key: item.path for key, item in inspection.metadata.items()} == {
        "service": "service",
        "version": "version",
    }
