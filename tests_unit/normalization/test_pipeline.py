from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime

import pytest

from journeygraph.domain import SourceRecord
from journeygraph.exceptions import ValidationError
from journeygraph.normalization import normalize_records, serialize_normalized_jsonl


def _event(
    step_id: str,
    timestamp: object,
    *,
    trace_id: str = "trace-1",
    parent_step_id: str | None = None,
    status: object = "ok",
    outcome: object = None,
    component: object = "component",
) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": "1.0",
        "trace_id": trace_id,
        "step_id": step_id,
        "timestamp": timestamp,
        "operation_type": "tool",
        "component": component,
        "duration_ms": 10,
        "status": status,
    }
    if parent_step_id is not None:
        result["parent_step_id"] = parent_step_id
    if outcome is not None:
        result["outcome"] = outcome
    return result


def _records(*events: dict[str, object]) -> tuple[SourceRecord, ...]:
    return tuple(
        SourceRecord(event, f"line {index}", index - 1) for index, event in enumerate(events, 1)
    )


def test_normalization_orders_deduplicates_and_keeps_retry_then_success_successful() -> None:
    # Arrange
    first = _event("a", "2026-07-21T12:00:00Z")
    failed_retry = _event("b", "2026-07-21T12:00:01Z", parent_step_id="a", status="error")
    success = _event(
        "c",
        "2026-07-21T12:00:02Z",
        parent_step_id="b",
        status="ok",
        outcome="success",
    )
    records = _records(success, failed_retry, first, failed_retry.copy())

    # Act
    dataset = normalize_records(records, input_format="jsonl")

    # Assert
    assert [event.step_id for event in dataset.events] == ["a", "b", "c"]
    assert dataset.traces[0].outcome == "success"
    assert dataset.traces[0].outcome_source == "explicit"
    assert {issue.code for issue in dataset.warnings} >= {
        "duplicate_event_removed",
        "out_of_order_input",
    }
    assert "disconnected_trace" not in {issue.code for issue in dataset.warnings}
    assert dataset.input_record_count == 4


def test_equal_timestamps_use_step_id_and_canonical_export_round_trips() -> None:
    # Arrange
    events = (
        _event("b", "2026-07-21T12:00:00.123456789Z", outcome="success"),
        _event("a", "2026-07-21T12:00:00.123456789Z"),
    )

    # Act
    dataset = normalize_records(_records(*events), input_format="jsonl")
    serialized = serialize_normalized_jsonl(dataset)

    # Assert
    assert [event.step_id for event in dataset.events] == ["a", "b"]
    assert "equal_timestamps" in {warning.code for warning in dataset.warnings}
    decoded = [json.loads(line) for line in serialized.splitlines()]
    assert [record["step_id"] for record in decoded] == ["a", "b"]
    assert all(record["schema_version"] == "1.0" for record in decoded)
    assert all(record["timestamp"].endswith(".123456789Z") for record in decoded)


def test_timezone_aware_parquet_datetime_is_accepted_but_naive_is_rejected() -> None:
    # Arrange
    aware = _event("a", datetime(2026, 7, 21, 12, tzinfo=UTC), outcome="success")
    naive = _event("a", datetime(2026, 7, 21, 12), outcome="success")

    # Act
    dataset = normalize_records(_records(aware), input_format="parquet")
    with pytest.raises(ValidationError) as captured:
        normalize_records(_records(naive), input_format="parquet")

    # Assert
    assert dataset.events[0].timestamp == datetime(2026, 7, 21, 12, tzinfo=UTC)
    assert captured.value.issues[0].code == "invalid_timestamp"


def test_parent_cycles_and_conflicting_duplicates_are_blocking() -> None:
    # Arrange
    cycle = _records(
        _event("a", "2026-07-21T12:00:00Z", parent_step_id="b"),
        _event("b", "2026-07-21T12:00:01Z", parent_step_id="a", outcome="success"),
    )
    duplicate_a = _event("a", "2026-07-21T12:00:00Z", outcome="success")
    duplicate_b = duplicate_a | {"duration_ms": 11}

    # Act
    with pytest.raises(ValidationError) as cycle_error:
        normalize_records(cycle, input_format="jsonl")
    with pytest.raises(ValidationError) as duplicate_error:
        normalize_records(_records(duplicate_a, duplicate_b), input_format="jsonl")

    # Assert
    assert {issue.code for issue in cycle_error.value.issues} == {"parent_cycle"}
    assert {issue.code for issue in duplicate_error.value.issues} == {"conflicting_duplicate_event"}


def test_relationship_quality_and_high_cardinality_are_reported_without_reordering_parents() -> (
    None
):
    # Arrange
    records = _records(
        _event("foreign", "2026-07-21T12:00:00Z", trace_id="trace-2", outcome="success"),
        _event("child", "2026-07-21T12:00:01Z", parent_step_id="late"),
        _event("late", "2026-07-21T12:00:02Z", component="other", outcome="success"),
        _event("missing", "2026-07-21T12:00:03Z", parent_step_id="foreign"),
    )

    # Act
    dataset = normalize_records(
        records,
        input_format="jsonl",
        high_cardinality_threshold=1,
    )

    # Assert
    codes = {warning.code for warning in dataset.warnings}
    assert {
        "cross_trace_parent",
        "disconnected_trace",
        "high_cardinality_categories",
        "parent_after_child",
    } <= codes
    trace_one = next(trace for trace in dataset.traces if trace.trace_id == "trace-1")
    assert [event.step_id for event in trace_one.events] == ["child", "late", "missing"]


@pytest.mark.parametrize(
    ("changes", "expected_code"),
    [
        ({"schema_version": "2.0"}, "unsupported_schema_version"),
        ({"schema_version": None}, "unsupported_schema_version"),
        ({"trace_id": "bad id"}, "invalid_identifier"),
        ({"step_id": ""}, "missing_identifier"),
        ({"parent_step_id": "bad id"}, "invalid_identifier"),
        ({"timestamp": "2026-07-21T12:00:00"}, "invalid_timestamp"),
        ({"operation_type": "9invalid"}, "invalid_operation_type"),
        ({"component": " "}, "invalid_component"),
        ({"component": "x" * 257}, "invalid_component"),
        ({"duration_ms": None}, "missing_numeric_value"),
        ({"duration_ms": True}, "invalid_numeric_value"),
        ({"duration_ms": -1}, "invalid_numeric_value"),
        ({"duration_ms": float("nan")}, "invalid_numeric_value"),
        ({"duration_ms": "1000000000000001"}, "numeric_value_out_of_range"),
        ({"duration_ms": "0.1234567890123456"}, "numeric_precision_unsupported"),
        ({"input_tokens": 1.5}, "invalid_integer_value"),
        ({"component": "bad\x01label"}, "invalid_component"),
        ({"component": chr(0xD800)}, "invalid_component"),
        ({"status": "bad"}, "invalid_status"),
        ({"outcome": "maybe"}, "invalid_outcome"),
    ],
)
def test_invalid_boundary_values_return_actionable_codes(
    changes: dict[str, object], expected_code: str
) -> None:
    # Arrange
    event = _event("a", "2026-07-21T12:00:00Z", outcome="success") | changes

    # Act
    with pytest.raises(ValidationError) as captured:
        normalize_records(_records(event), input_format="jsonl")

    # Assert
    codes = {issue.code for issue in captured.value.issues}
    assert expected_code in codes
    assert all(issue.hint for issue in captured.value.issues)


def test_permuting_rows_never_changes_normalized_analytical_events() -> None:
    # Arrange
    events = (
        _event("a", "2026-07-21T12:00:00Z"),
        _event("b", "2026-07-21T12:00:01Z", parent_step_id="a"),
        _event("c", "2026-07-21T12:00:02Z", parent_step_id="b", outcome="success"),
    )

    # Act
    outputs = {
        serialize_normalized_jsonl(normalize_records(_records(*permutation), input_format="jsonl"))
        for permutation in itertools.permutations(events)
    }

    # Assert
    assert len(outputs) == 1


def test_pre_epoch_aware_datetimes_keep_exact_chronological_order() -> None:
    # Arrange
    before_epoch = _event("before", datetime(1969, 12, 31, 23, 59, 59, 500_000, tzinfo=UTC))
    after_epoch = _event(
        "after",
        datetime(1970, 1, 1, 0, 0, 0, 100_000, tzinfo=UTC),
        outcome="success",
    )

    # Act
    dataset = normalize_records(_records(after_epoch, before_epoch), input_format="parquet")

    # Assert
    assert [event.step_id for event in dataset.events] == ["before", "after"]
    assert [event.timestamp_ns for event in dataset.events] == [-500_000_000, 100_000_000]


def test_accepted_csv_boundaries_preserve_offsets_precision_and_blank_optionals() -> None:
    # Arrange
    event = _event(
        "boundary",
        "2026-07-21T14:30:00.1+02:30",
        component="x" * 256,
        outcome="",
    ) | {
        "duration_ms": "1000000000000000",
        "input_tokens": "",
        "output_tokens": "",
        "cost_usd": "0.123456789012345",
    }

    # Act
    dataset = normalize_records(_records(event), input_format="csv")
    serialized = json.loads(serialize_normalized_jsonl(dataset))

    # Assert
    accepted = dataset.events[0]
    assert accepted.timestamp_ns == 1_784_635_200_100_000_000
    assert accepted.timestamp.tzinfo is UTC
    assert serialized["timestamp"] == "2026-07-21T12:00:00.100000Z"
    assert serialized["duration_ms"] == 1_000_000_000_000_000
    assert serialized["cost_usd"] == 0.123456789012345
    assert "input_tokens" not in serialized
    assert "output_tokens" not in serialized
    assert "outcome" not in serialized
    assert len(serialized["component"]) == 256


def test_aware_datetime_is_normalized_to_the_utc_timezone_object() -> None:
    # Arrange
    timestamp = datetime.fromisoformat("2026-07-21T17:30:00.123456+05:30")
    event = _event("aware", timestamp, outcome="success")

    # Act
    dataset = normalize_records(_records(event), input_format="parquet")

    # Assert
    accepted = dataset.events[0]
    assert accepted.timestamp == datetime(2026, 7, 21, 12, 0, 0, 123456, tzinfo=UTC)
    assert accepted.timestamp.tzinfo is UTC
