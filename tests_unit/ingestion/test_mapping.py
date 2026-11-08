"""Unit tests for mapping-document parsing and record mapping."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from journeygraph.domain.models import SourceRecord
from journeygraph.exceptions import FileOperationError, UsageError, ValidationError
from journeygraph.ingestion.mapping import (
    MappingError,
    apply_mapping,
    ignored_fields_warning,
    load_mapping,
    parse_mapping,
    parse_path,
)

_REQUIRED = """
mapping_version = "1"
[fields]
trace_id = "t"
step_id = "s"
timestamp = "at"
operation_type = "kind"
component = "name"
status = "state"
"""


def _mapping(extra: str = "", *, duration: str = 'duration_ms = "ms"\n') -> str:
    return _REQUIRED + duration + extra


def _record(data: dict[str, object], index: int = 0) -> SourceRecord:
    return SourceRecord(data, f"line {index + 1}", index)


def _base(**values: object) -> dict[str, object]:
    data: dict[str, object] = {
        "t": "trace-1",
        "s": "step-1",
        "at": "2026-09-21T10:00:00Z",
        "kind": "tool",
        "name": "search",
        "ms": 5,
        "state": "ok",
    }
    data.update(values)
    return data


@pytest.mark.parametrize(
    ("text", "segments"),
    [
        ("a", ("a",)),
        ("a.b.c", ("a", "b", "c")),
        ('attributes."tool.name"', ("attributes", "tool.name")),
        ('"a.b".c', ("a.b", "c")),
        ('""', ("",)),
    ],
)
def test_parse_path_splits_dots_outside_quotes(text: str, segments: tuple[str, ...]) -> None:
    assert parse_path(text).segments == segments
    assert parse_path(text).text == text


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("a..b", "empty segment"),
        (".a", "empty segment"),
        ("a.", "empty segment"),
        ('a."b', "unterminated quote"),
        ('a"b"', "misplaced quote"),
        ('"a"b', "text after a closing quote"),
        ('"a""b"', "misplaced quote"),
    ],
)
def test_parse_path_rejects_malformed_paths(text: str, message: str) -> None:
    with pytest.raises(MappingError, match=message):
        parse_path(text)


def test_mapping_builds_canonical_records_with_values_constants_and_metadata() -> None:
    # Arrange
    mapping = parse_mapping(
        _REQUIRED.replace('operation_type = "kind"\n', "")
        + 'duration_ms = "ms"\noutcome = "result.value"\n'
        + '[constants]\noperation_type = "TOOL"\n'
        + '[values.operation_type]\nTOOL = "tool"\n'
        + '[values.status]\n2 = "error"\n'
        + '[values.outcome]\nOK = "success"\n'
        + '[metadata]\nenvironment = "env.name"\n'
    )
    record = _record(_base(state=2, result={"value": "OK"}, env={"name": "prod"}, extra=1))

    # Act
    mapped = apply_mapping([record], mapping)

    # Assert
    data = dict(mapped.records[0].data)
    assert data == {
        "schema_version": "1.0",
        "operation_type": "tool",
        "trace_id": "trace-1",
        "step_id": "step-1",
        "timestamp": "2026-09-21T10:00:00Z",
        "component": "search",
        "status": "error",
        "duration_ms": 5,
        "outcome": "success",
        "metadata": {"environment": "prod"},
    }
    assert mapped.records[0].location == "line 1"
    assert mapped.ignored_path_count == 2  # "kind" and "extra" were not read


def test_unmatched_values_and_booleans_pass_through_unchanged() -> None:
    mapping = parse_mapping(_mapping('[values.status]\nOK = "ok"\n'))
    first = apply_mapping([_record(_base(state="weird"))], mapping).records[0].data
    second = apply_mapping([_record(_base(state=True))], mapping).records[0].data
    assert first["status"] == "weird"
    assert second["status"] is True


def test_top_level_keys_with_dots_are_matched_before_nested_paths() -> None:
    mapping = parse_mapping(_REQUIRED.replace('"name"', '"tool.name"') + 'duration_ms = "ms"\n')
    data = apply_mapping([_record(_base(**{"tool.name": "flat"}))], mapping).records[0].data
    assert data["component"] == "flat"


@pytest.mark.parametrize(
    ("unit", "value", "timestamp", "timestamp_ns"),
    [
        ("unix_s", 1_790_000_000, "2026-09-21T14:13:20.000000000Z", 1_790_000_000_000_000_000),
        ("unix_s", "1790000000.5", "2026-09-21T14:13:20.500000000Z", 1_790_000_000_500_000_000),
        ("unix_ms", 1_790_000_000_123, "2026-09-21T14:13:20.123000000Z", 1_790_000_000_123_000_000),
        (
            "unix_us",
            1_790_000_000_000_001,
            "2026-09-21T14:13:20.000001000Z",
            1_790_000_000_000_001_000,
        ),
        (
            "unix_ns",
            "1790000000000000001",
            "2026-09-21T14:13:20.000000001Z",
            1_790_000_000_000_000_001,
        ),
        ("unix_s", 1_790_000_000.25, "2026-09-21T14:13:20.250000000Z", 1_790_000_000_250_000_000),
    ],
)
def test_epoch_timestamps_convert_exactly(
    unit: str, value: object, timestamp: str, timestamp_ns: int
) -> None:
    # Arrange
    mapping = parse_mapping(_mapping(f'[timestamp]\nunit = "{unit}"\n'))

    # Act
    record = apply_mapping([_record(_base(at=value))], mapping).records[0]

    # Assert
    assert record.data["timestamp"] == timestamp
    assert record.timestamp_ns == timestamp_ns


@pytest.mark.parametrize("value", ["soon", True, None, 1.5e400, "1790000000.0000000001", 10**30])
def test_invalid_epoch_timestamps_are_validation_errors(value: object) -> None:
    mapping = parse_mapping(_mapping('[timestamp]\nunit = "unix_s"\n'))
    with pytest.raises(ValidationError) as caught:
        apply_mapping([_record(_base(at=value))], mapping)
    issue = caught.value.issues[0]
    assert issue.code == "mapped_value_invalid"
    assert issue.location == "line 1.timestamp"
    assert "'at'" in issue.message


@pytest.mark.parametrize(
    ("unit", "value", "expected"),
    [("s", "1.5", "1500"), ("us", 2500, "2.5"), ("ns", 3_000_000, "3"), ("ms", "7", "7")],
)
def test_single_duration_fields_convert_to_milliseconds(
    unit: str, value: object, expected: str
) -> None:
    mapping = parse_mapping(_mapping(f'[duration]\nfield = "lat"\nunit = "{unit}"\n', duration=""))
    data = apply_mapping([_record(_base(lat=value))], mapping).records[0].data
    assert str(data["duration_ms"]) == expected


def test_non_numeric_duration_with_a_unit_is_an_error_and_missing_one_is_left_out() -> None:
    mapping = parse_mapping(_mapping('[duration]\nfield = "lat"\nunit = "s"\n', duration=""))
    with pytest.raises(ValidationError, match="is not numeric"):
        apply_mapping([_record(_base(lat="slow"))], mapping)
    data = apply_mapping([_record(_base())], mapping).records[0].data
    assert "duration_ms" not in data


@pytest.mark.parametrize(
    ("unit", "start", "end", "expected"),
    [
        ("iso8601", "2026-09-21T10:00:00Z", "2026-09-21T10:00:01.25Z", "1250"),
        (
            "iso8601",
            "2026-09-21T10:00:00.000000001+00:00",
            "2026-09-21T10:00:00.000000003Z",
            "0.000002",
        ),
        ("unix_ms", 1000, 1000, "0"),
        ("unix_ns", 0, 1_500_000, "1.5"),
        ("unix_ms", 2000, 1000, "-1000"),
    ],
)
def test_duration_pairs_subtract_instants_in_the_timestamp_unit(
    unit: str, start: object, end: object, expected: str
) -> None:
    # Arrange
    duration = '[duration]\nstart = "begin"\nend = "finish"\n'
    timestamp = f'[timestamp]\nunit = "{unit}"\n' if unit != "iso8601" else ""
    mapping = parse_mapping(_mapping(timestamp + duration, duration=""))
    at = start if unit != "iso8601" else "2026-09-21T10:00:00Z"

    # Act
    data = apply_mapping([_record(_base(at=at, begin=start, finish=end))], mapping).records[0].data

    # Assert
    assert data["duration_ms"] == expected


def test_duration_pairs_accept_aware_datetimes_and_reject_naive_ones() -> None:
    mapping = parse_mapping(_mapping('[duration]\nstart = "begin"\nend = "finish"\n', duration=""))
    begin = datetime(2026, 9, 21, 10, tzinfo=UTC)
    finish = datetime(2026, 9, 21, 10, 0, 2, tzinfo=UTC)
    data = apply_mapping([_record(_base(begin=begin, finish=finish))], mapping).records[0].data
    assert data["duration_ms"] == "2000"
    with pytest.raises(ValidationError, match="must both be iso8601 instants"):
        apply_mapping([_record(_base(begin=begin.replace(tzinfo=None), finish=finish))], mapping)


@pytest.mark.parametrize(
    "begin", ["yesterday", "2026-13-40T10:00:00Z", "2026-09-21T10:00:00", 12, None]
)
def test_duration_pairs_reject_values_that_are_not_instants(begin: object) -> None:
    mapping = parse_mapping(_mapping('[duration]\nstart = "begin"\nend = "finish"\n', duration=""))
    with pytest.raises(ValidationError) as caught:
        apply_mapping([_record(_base(begin=begin, finish="2026-09-21T10:00:00Z"))], mapping)
    assert caught.value.issues[0].location == "line 1.duration_ms"
    assert "begin / finish" in caught.value.issues[0].message


def test_missing_required_and_optional_paths() -> None:
    mapping = parse_mapping(_REQUIRED + 'duration_ms = "ms"\noutcome = "result"\n')
    data = dict(_base())
    del data["t"]
    with pytest.raises(ValidationError) as caught:
        apply_mapping([_record(_base()), _record(data, 1)], mapping)
    assert [issue.code for issue in caught.value.issues] == ["mapped_field_missing"]
    assert caught.value.issues[0].location == "line 2.trace_id"
    assert "'t'" in caught.value.issues[0].message
    ok = apply_mapping([_record(_base())], mapping).records[0].data
    assert "outcome" not in ok


def test_nested_lookups_stop_at_non_objects_and_count_leaves() -> None:
    mapping = parse_mapping(_REQUIRED.replace('"name"', '"a.b"') + 'duration_ms = "ms"\n')
    with pytest.raises(ValidationError, match=r"'a\.b'"):
        apply_mapping([_record(_base(a="scalar"))], mapping)
    mapped = apply_mapping(
        [_record(_base(a={"b": "x", "c": {"d": 1, "e": {}}}, f=[1, 2]))], mapping
    )
    assert mapped.records[0].data["component"] == "x"
    # name, a.c.d, the empty object a.c.e, and the list f were not read.
    assert mapped.ignored_path_count == 4
    assert ("a", "b") in mapped.used_paths


def test_ignored_count_is_distinct_across_records() -> None:
    mapping = parse_mapping(_mapping())
    records = [_record(_base(extra=1)), _record(_base(extra=2, other=3), 1)]
    assert apply_mapping(records, mapping).ignored_path_count == 2
    repeated = [_record(_base(extra=1)), _record(_base(extra=1), 1)]
    assert apply_mapping(repeated, mapping).ignored_path_count == 1


def test_ignored_fields_warning_names_only_a_count() -> None:
    warning = ignored_fields_warning(3)
    assert warning.severity == "warning"
    assert warning.code == "unmapped_source_fields_ignored"
    assert "3 distinct" in warning.message


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("mapping_version = 2", 'mapping_version must be "1"'),
        ('mapping_version = "1"\n[filed]\n', "unknown key"),
        ("[fields", "invalid TOML"),
        ('mapping_version = "1"\nfields = 1', "fields must be a table"),
        (_mapping("[fields.x]\n"), "must be a non-empty source path string"),
        (_mapping().replace('"t"', '""'), "must be a non-empty source path string"),
        (_mapping('[constants]\nstep_id = "x"\n'), "both mapped and constant: step_id"),
        (_mapping('[constants]\ncolour = "x"\n'), "unknown canonical field"),
        (_mapping().replace('trace_id = "t"', 'trace = "t"'), "unknown canonical field"),
        (_mapping("[constants]\noutcome = true\n"), "must be a string or number"),
        (_mapping('[metadata]\n" " = "x"\n'), "metadata keys must be non-empty"),
        (_mapping('[values.component]\na = "b"\n'), "values.component is not supported"),
        (_mapping("[values]\nstatus = 1\n"), "values.status must be a table"),
        (_mapping("[values.status]\nOK = 1\n"), "must be a string"),
        (_mapping('[timestamp]\nunit = "hours"\n'), "timestamp.unit must be one of"),
        (_mapping('[timestamp]\nformat = "x"\n'), "timestamp accepts only unit"),
        (_mapping('[duration]\nfield = "x"\n'), "not both"),
        (_mapping('[duration]\nfield = "x"\nunit = "h"\n', duration=""), "duration.unit"),
        (_mapping('[duration]\nfield = ""\n', duration=""), "non-empty strings"),
        (_mapping('[duration]\nstart = "a"\n', duration=""), "field (with optional unit)"),
        (_mapping('[duration]\nstart = "a"\nend = "b"\nunit = "s"\n', duration=""), "field (with"),
        (_mapping('[duration]\nlength = "a"\n', duration=""), "duration accepts only"),
        (_REQUIRED, "required field(s) not mapped: duration_ms"),
        (
            _REQUIRED.replace('timestamp = "at"\n', "") + 'duration_ms = "ms"\n[constants]\n'
            'timestamp = "2026-01-01T00:00:00Z"\n',
            "timestamp cannot be a constant",
        ),
    ],
)
def test_parse_mapping_rejects_invalid_documents(text: str, message: str) -> None:
    with pytest.raises(MappingError, match=message.replace("(", r"\(").replace(")", r"\)")):
        parse_mapping(text)


def test_load_mapping_maps_errors_to_usage_and_file_failures(tmp_path: Path) -> None:
    good = tmp_path / "good.toml"
    good.write_text(_mapping(), encoding="utf-8")
    assert load_mapping(good).fields["trace_id"].text == "t"
    bad = tmp_path / "bad.toml"
    bad.write_text("mapping_version = 2", encoding="utf-8")
    with pytest.raises(UsageError, match="invalid mapping file"):
        load_mapping(bad)
    binary = tmp_path / "binary.toml"
    binary.write_bytes(b"\xff\xfe")
    with pytest.raises(UsageError, match="not UTF-8"):
        load_mapping(binary)
    with pytest.raises(FileOperationError, match="cannot read mapping file"):
        load_mapping(tmp_path / "absent.toml")


@pytest.mark.parametrize(
    ("text", "segments"),
    [
        ("ids[0]", ("ids", 0)),
        ("ids[-1]", ("ids", -1)),
        ("a.ids[2].name", ("a", "ids", 2, "name")),
        ('"x.y"[1]', ("x.y", 1)),
        ('"a[0]"', ("a[0]",)),
    ],
)
def test_parse_path_reads_array_indexes(text: str, segments: tuple[object, ...]) -> None:
    assert parse_path(text).segments == segments


@pytest.mark.parametrize("text", ["ids[x]", "ids[0", "[0]", "ids[0]x", '"a"[0', "a]"])
def test_parse_path_rejects_malformed_indexes(text: str) -> None:
    with pytest.raises(MappingError):
        parse_path(text)


def test_indexed_paths_read_array_elements_and_count_the_array_as_used() -> None:
    # Arrange
    mapping = parse_mapping(_mapping('parent_step_id = "ancestors[-1]"\n'))
    records = [
        _record(_base(ancestors=["root", "parent"])),
        _record(_base(ancestors=[]), 1),
        _record(_base(ancestors="not-a-list"), 2),
    ]

    # Act
    mapped = apply_mapping(records, mapping)

    # Assert
    assert mapped.records[0].data["parent_step_id"] == "parent"
    assert "parent_step_id" not in mapped.records[1].data
    assert "parent_step_id" not in mapped.records[2].data
    assert mapped.ignored_path_count == 0
    assert parse_path("ancestors[-1]").key_prefix == ("ancestors",)
