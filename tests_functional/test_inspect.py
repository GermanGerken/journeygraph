"""Black-box acceptance tests for ``journeygraph inspect``."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests_functional.helpers import CommandResult, assert_no_traceback, read_jsonl

# Values that occur in the fixtures and must never appear in default inspect output.
_FIXTURE_VALUES = (
    "session-1",
    "span-1-1",
    "STATUS_CODE_OK",
    "planner",
    "prod",
    "synthetic prompt text",
    "1790000000000",
    "2026-09-21T14:13:20",
)


def _structure(events: list[dict[str, object]]) -> list[tuple[object, ...]]:
    return [
        (
            event["trace_id"],
            event["step_id"],
            event.get("parent_step_id"),
            event["timestamp"],
            event["duration_ms"],
            event.get("outcome"),
            event.get("cost_usd"),
        )
        for event in events
    ]


def test_inspect_reports_paths_without_values(
    cli: Callable[..., CommandResult], fixture_dir: Path
) -> None:
    # Act
    result = cli("inspect", fixture_dir / "mapped_export.jsonl")

    # Assert
    result.assert_exit(0)
    assert "inspected: 18 of 18 record(s); 14 source path(s)" in result.stdout
    assert "session.id" in result.stdout
    assert 'attributes."tool.name"' in result.stdout
    assert "missing required fields: none" in result.stdout
    for value in _FIXTURE_VALUES:
        assert value not in result.stdout
    assert_no_traceback(result)


def test_jsonl_draft_with_show_values_validates_unchanged(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    draft = tmp_path / "mapping.toml"

    # Act
    inspected = cli(
        "inspect",
        fixture_dir / "mapped_export.jsonl",
        "--show-values",
        "--mapping-out",
        draft,
    )
    mapped = cli(
        "validate",
        fixture_dir / "mapped_export.jsonl",
        "--mapping",
        draft,
        "--normalized-out",
        tmp_path / "mapped.jsonl",
    )
    canonical = cli(
        "validate",
        fixture_dir / "mapped_canonical.jsonl",
        "--normalized-out",
        tmp_path / "canonical.jsonl",
    )

    # Assert: same journeys; only the operation-type labels may differ from the hand mapping.
    inspected.assert_exit(0)
    mapped.assert_exit(0)
    canonical.assert_exit(0)
    assert "observed status tokens: STATUS_CODE_ERROR, STATUS_CODE_OK" in inspected.stdout
    assert _structure(read_jsonl(tmp_path / "mapped.jsonl")) == _structure(
        read_jsonl(tmp_path / "canonical.jsonl")
    )
    statuses = [event["status"] for event in read_jsonl(tmp_path / "mapped.jsonl")]
    assert statuses == [event["status"] for event in read_jsonl(tmp_path / "canonical.jsonl")]
    text = draft.read_text(encoding="utf-8")
    assert "synthetic prompt text" not in text
    assert "llm.prompt" not in text


def test_csv_draft_leaves_unrecognized_status_codes_as_todo(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange: the CSV export encodes status as 1 and 2, which no heuristic can name.
    draft = tmp_path / "mapping.toml"

    # Act
    inspected = cli(
        "inspect", fixture_dir / "mapped_export.csv", "--show-values", "--mapping-out", draft
    )
    validated = cli("validate", fixture_dir / "mapped_export.csv", "--mapping", draft)

    # Assert
    inspected.assert_exit(0)
    text = draft.read_text(encoding="utf-8")
    assert '# "1" = ""  # TODO' in text
    assert 'field = "latency_s"\nunit = "s"' in text
    validated.assert_exit(2)
    assert "status" in validated.stderr
    assert_no_traceback(validated)


def test_draft_without_show_values_contains_no_value_maps(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    draft = tmp_path / "mapping.toml"

    # Act
    result = cli("inspect", fixture_dir / "mapped_export.jsonl", "--mapping-out", draft)

    # Assert
    result.assert_exit(0)
    text = draft.read_text(encoding="utf-8")
    assert "# [values.status]" in text
    assert "STATUS_CODE" not in text
    for value in _FIXTURE_VALUES:
        assert value not in text


def test_draft_with_missing_required_fields_keeps_todo_lines(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange: nothing here looks like a trace identifier or a status.
    export = tmp_path / "export.jsonl"
    export.write_text('{"a": 1, "b": "x"}\n{"a": 2, "b": "y"}\n', encoding="utf-8")
    draft = tmp_path / "mapping.toml"

    # Act
    inspected = cli("inspect", export, "--mapping-out", draft)
    validated = cli("validate", export, "--mapping", draft)

    # Assert
    inspected.assert_exit(0)
    assert "missing required fields: trace_id, step_id, timestamp" in inspected.stdout
    assert '# trace_id = ""  # TODO: required' in draft.read_text(encoding="utf-8")
    validated.assert_exit(2)
    assert "required field(s) not mapped" in validated.stderr


@pytest.mark.parametrize(
    ("arguments", "code", "message"),
    [
        (("--sample", "0"), 2, "expected a positive integer"),
        (("--format", "otlp-json"), 2, "invalid choice"),
    ],
)
def test_inspect_rejects_invalid_options(
    cli: Callable[..., CommandResult],
    fixture_dir: Path,
    arguments: tuple[str, ...],
    code: int,
    message: str,
) -> None:
    result = cli("inspect", fixture_dir / "mapped_export.jsonl", *arguments)
    result.assert_exit(code)
    assert message in result.stderr
    assert_no_traceback(result)


def test_inspect_respects_sample_size_and_output_safety(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    draft = tmp_path / "mapping.toml"
    draft.write_text("existing\n", encoding="utf-8")

    # Act
    sampled = cli("inspect", fixture_dir / "mapped_export.jsonl", "--sample", "3")
    conflict = cli("inspect", fixture_dir / "mapped_export.jsonl", "--mapping-out", draft)
    after_conflict = draft.read_text(encoding="utf-8")
    forced = cli("inspect", fixture_dir / "mapped_export.jsonl", "--mapping-out", draft, "--force")
    same_as_input = cli(
        "inspect",
        fixture_dir / "mapped_export.jsonl",
        "--mapping-out",
        fixture_dir / "mapped_export.jsonl",
        "--force",
    )

    # Assert
    sampled.assert_exit(0)
    assert "inspected: 3 of 18 record(s)" in sampled.stdout
    conflict.assert_exit(4)
    assert after_conflict == "existing\n"
    forced.assert_exit(0)
    assert draft.read_text(encoding="utf-8").startswith("# Draft field mapping")
    same_as_input.assert_exit(4)
    assert (fixture_dir / "mapped_export.jsonl").read_text(encoding="utf-8").startswith("{")
