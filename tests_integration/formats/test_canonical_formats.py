from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from journeygraph.api import analyze_file, validate_file, write_analysis
from journeygraph.exceptions import FormatError
from journeygraph.ingestion import read_records


def _canonical_records() -> list[dict[str, object]]:
    return [
        {
            "schema_version": "1.0",
            "trace_id": "trace-format-equivalence",
            "step_id": "request-1",
            "parent_step_id": None,
            "timestamp": "2026-01-02T03:04:05.123456Z",
            "operation_type": "request",
            "component": "Public API",
            "duration_ms": "2.5",
            "status": "ok",
            "outcome": None,
            "input_tokens": "5",
            "output_tokens": "0",
            "cost_usd": "0.001",
            "metadata": {
                "cohort": "canary",
                "environment": "integration",
                "service": "edge",
            },
        },
        {
            "schema_version": "1.0",
            "trace_id": "trace-format-equivalence",
            "step_id": "tool-1",
            "parent_step_id": "request-1",
            "timestamp": "2026-01-02T03:04:05.126956Z",
            "operation_type": "tool",
            "component": "Catalog lookup",
            "duration_ms": "3.5",
            "status": "ok",
            "outcome": "success",
            "input_tokens": "8",
            "output_tokens": "13",
            "cost_usd": "0.004",
            "metadata": {
                "cohort": "canary",
                "environment": "integration",
                "service": "edge",
            },
        },
    ]


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    content = "".join(f"{json.dumps(record, sort_keys=True)}\n" for record in records)
    path.write_text(content, encoding="utf-8")


def _write_csv(path: Path, records: list[dict[str, object]]) -> None:
    fieldnames = [
        "schema_version",
        "trace_id",
        "step_id",
        "parent_step_id",
        "timestamp",
        "operation_type",
        "component",
        "duration_ms",
        "status",
        "outcome",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "metadata.cohort",
        "metadata.environment",
        "metadata.service",
    ]
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            metadata = record["metadata"]
            assert isinstance(metadata, dict)
            flattened = {key: value for key, value in record.items() if key != "metadata"}
            flattened.update({f"metadata.{key}": value for key, value in metadata.items()})
            writer.writerow(flattened)


def _dataset_meaning(dataset: Any) -> tuple[object, ...]:
    return (
        [event.to_dict() for event in dataset.events],
        [
            (
                trace.trace_id,
                trace.outcome,
                trace.outcome_source,
                tuple(event.step_id for event in trace.events),
            )
            for trace in dataset.traces
        ],
        [warning.to_dict() for warning in dataset.warnings],
        dataset.input_record_count,
    )


def test_jsonl_and_csv_produce_equivalent_normalized_datasets(tmp_path: Path) -> None:
    # Arrange
    records = _canonical_records()
    jsonl_path = tmp_path / "journey.jsonl"
    csv_path = tmp_path / "journey.csv"
    _write_jsonl(jsonl_path, records)
    _write_csv(csv_path, records)

    # Act
    jsonl_dataset = validate_file(jsonl_path, input_format="jsonl")
    csv_dataset = validate_file(csv_path, input_format="csv")

    # Assert
    assert jsonl_dataset.input_format == "jsonl"
    assert csv_dataset.input_format == "csv"
    assert _dataset_meaning(jsonl_dataset) == _dataset_meaning(csv_dataset)


def test_real_parquet_round_trip_matches_jsonl_when_pyarrow_is_installed(
    tmp_path: Path,
) -> None:
    # Arrange
    pyarrow = pytest.importorskip("pyarrow", reason="Parquet support is optional")
    parquet = pytest.importorskip("pyarrow.parquet", reason="Parquet support is optional")
    records = _canonical_records()
    jsonl_path = tmp_path / "journey.jsonl"
    parquet_path = tmp_path / "journey.parquet"
    _write_jsonl(jsonl_path, records)
    parquet.write_table(pyarrow.Table.from_pylist(records), parquet_path)

    # Act
    jsonl_dataset = validate_file(jsonl_path, input_format="jsonl")
    parquet_dataset = validate_file(parquet_path, input_format="parquet")

    # Assert
    assert parquet_dataset.input_format == "parquet"
    assert _dataset_meaning(parquet_dataset) == _dataset_meaning(jsonl_dataset)


@pytest.mark.parametrize(
    ("unit", "raw_timestamp", "expected_ns", "expected_timestamp"),
    [
        ("s", 1_767_225_600, 1_767_225_600_000_000_000, "2026-01-01T00:00:00.000000Z"),
        (
            "ms",
            1_767_225_600_123,
            1_767_225_600_123_000_000,
            "2026-01-01T00:00:00.123000Z",
        ),
        (
            "us",
            1_767_225_600_123_456,
            1_767_225_600_123_456_000,
            "2026-01-01T00:00:00.123456Z",
        ),
        (
            "ns",
            1_767_225_600_123_456_789,
            1_767_225_600_123_456_789,
            "2026-01-01T00:00:00.123456789Z",
        ),
        ("ns", -1, -1, "1969-12-31T23:59:59.999999999Z"),
    ],
)
def test_real_parquet_timestamp_preserves_epoch_units_and_submicrosecond_precision(
    tmp_path: Path,
    unit: str,
    raw_timestamp: int,
    expected_ns: int,
    expected_timestamp: str,
) -> None:
    # Arrange
    pyarrow = pytest.importorskip("pyarrow", reason="Parquet support is optional")
    parquet = pytest.importorskip("pyarrow.parquet", reason="Parquet support is optional")
    parquet_path = tmp_path / f"timestamp-{unit}.parquet"
    table = pyarrow.table(
        {
            "schema_version": ["1.0"],
            "trace_id": [f"trace-{unit}"],
            "step_id": ["step-1"],
            "timestamp": pyarrow.array(
                [raw_timestamp], type=pyarrow.timestamp(unit, tz="Asia/Kolkata")
            ),
            "operation_type": ["request"],
            "component": ["Parquet timestamp"],
            "duration_ms": [1],
            "status": ["ok"],
            "outcome": ["success"],
        }
    )
    parquet.write_table(table, parquet_path)

    # Act
    source_records = read_records(parquet_path, input_format="parquet")
    dataset = validate_file(parquet_path, input_format="parquet")

    # Assert
    assert len(source_records) == 1
    assert source_records[0].timestamp_ns == expected_ns
    assert len(dataset.events) == 1
    assert dataset.events[0].timestamp_ns == expected_ns
    assert dataset.events[0].to_dict()["timestamp"] == expected_timestamp


def test_parquet_row_conversion_failure_is_an_actionable_format_error(
    tmp_path: Path,
) -> None:
    # Arrange
    pyarrow = pytest.importorskip("pyarrow", reason="Parquet support is optional")
    parquet = pytest.importorskip("pyarrow.parquet", reason="Parquet support is optional")
    parquet_path = tmp_path / "invalid-timezone.parquet"
    table = pyarrow.table(
        {
            "schema_version": ["1.0"],
            "trace_id": ["trace-invalid-timezone"],
            "step_id": ["step-1"],
            "timestamp": pyarrow.array(
                [1_767_225_600_000_000_123],
                type=pyarrow.timestamp("ns", tz="Mars/Olympus"),
            ),
            "operation_type": ["request"],
            "component": ["Invalid timezone"],
            "duration_ms": [1],
            "status": ["ok"],
        }
    )
    parquet.write_table(table, parquet_path)

    # Act
    with pytest.raises(FormatError) as exc_info:
        validate_file(parquet_path, input_format="parquet")

    # Assert
    message = str(exc_info.value)
    assert "[invalid_parquet_values]" in message
    assert "row" in message.lower()
    assert "Fix:" in message


def test_parquet_with_wrong_schema_reports_required_columns_when_pyarrow_is_installed(
    tmp_path: Path,
) -> None:
    # Arrange
    pyarrow = pytest.importorskip("pyarrow", reason="Parquet support is optional")
    parquet = pytest.importorskip("pyarrow.parquet", reason="Parquet support is optional")
    parquet_path = tmp_path / "wrong-schema.parquet"
    parquet.write_table(pyarrow.table({"unexpected": ["value"]}), parquet_path)

    # Act
    with pytest.raises(Exception) as exc_info:
        validate_file(parquet_path, input_format="parquet")

    # Assert
    message = str(exc_info.value)
    assert exc_info.type.__name__ == "FormatError"
    assert "[missing_parquet_columns]" in message
    assert "schema_version" in message
    assert "trace_id" in message
    assert "Fix:" in message


def test_canonical_artifact_can_be_reimported_without_changing_meaning(tmp_path: Path) -> None:
    # Arrange
    input_path = tmp_path / "source.jsonl"
    output_dir = tmp_path / "analysis"
    _write_jsonl(input_path, _canonical_records())
    analysis = analyze_file(input_path, input_format="jsonl")

    # Act
    artifacts = write_analysis(analysis, output_dir)
    reimported = validate_file(artifacts.normalized_jsonl, input_format="jsonl")

    # Assert
    assert artifacts.normalized_jsonl.is_file()
    assert _dataset_meaning(reimported) == _dataset_meaning(analysis.dataset)


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        (
            "schema_version,trace_id,step_id,timestamp,operation_type,component,duration_ms,status,status\n"
            "1.0,t,s,2026-01-01T00:00:00Z,request,start,1,ok,ok\n",
            "invalid_csv_header",
        ),
        (
            "schema_version,trace_id,step_id,timestamp,operation_type,component,duration_ms,status\n"
            "1.0,t,s,2026-01-01T00:00:00Z,request,start,1,ok,extra\n",
            "extra_csv_values",
        ),
    ],
)
def test_csv_rejects_ambiguous_or_overwide_rows(
    tmp_path: Path, content: str, expected_code: str
) -> None:
    # Arrange
    input_path = tmp_path / "invalid.csv"
    input_path.write_text(content, encoding="utf-8")

    # Act / Assert
    with pytest.raises(FormatError, match=expected_code):
        validate_file(input_path, input_format="csv")


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        (b"\xff\xfe\x00", "invalid_utf8"),
        (
            b'{"schema_version":"1.0","trace_id":"t","step_id":"s",'
            b'"timestamp":"2026-01-01T00:00:00Z","operation_type":"request",'
            b'"component":"start","duration_ms":' + b"9" * 5_000 + b',"status":"ok"}\n',
            "invalid_json_value",
        ),
    ],
)
def test_jsonl_decode_failures_are_format_errors(
    tmp_path: Path, content: bytes, expected_code: str
) -> None:
    # Arrange
    input_path = tmp_path / "invalid.jsonl"
    input_path.write_bytes(content)

    # Act / Assert
    with pytest.raises(FormatError, match=expected_code):
        validate_file(input_path, input_format="jsonl")
