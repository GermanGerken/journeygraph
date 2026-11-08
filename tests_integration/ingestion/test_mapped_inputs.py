"""Integration tests: mapped JSON Lines, CSV, and Parquet inputs through the public API."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pytest

from journeygraph.api import analyze_file, load_mapping, validate_file
from journeygraph.exceptions import FormatError, UsageError, ValidationError
from journeygraph.normalization import serialize_normalized_jsonl

FIXTURES = Path(__file__).resolve().parents[2] / "tests_functional" / "fixtures"
CANONICAL = FIXTURES / "mapped_canonical.jsonl"


def _canonical_events() -> str:
    return serialize_normalized_jsonl(validate_file(CANONICAL))


@pytest.mark.parametrize(
    ("export", "mapping"),
    [
        ("mapped_export.jsonl", "mapped_export.mapping.toml"),
        ("mapped_export.csv", "mapped_export.csv.mapping.toml"),
    ],
)
def test_mapped_exports_normalize_to_the_canonical_events(export: str, mapping: str) -> None:
    # Act
    dataset = validate_file(FIXTURES / export, mapping=FIXTURES / mapping)

    # Assert
    assert serialize_normalized_jsonl(dataset) == _canonical_events()


def test_a_parsed_mapping_object_is_reused_and_analysis_matches(tmp_path: Path) -> None:
    # Arrange
    mapping = load_mapping(FIXTURES / "mapped_export.mapping.toml")

    # Act
    mapped = analyze_file(FIXTURES / "mapped_export.jsonl", mapping=mapping).report
    canonical = analyze_file(CANONICAL).report

    # Assert
    assert mapped["nodes"] == canonical["nodes"]
    assert mapped["paths"] == canonical["paths"]
    assert mapped["findings"] == canonical["findings"]
    codes = [warning["code"] for warning in mapped["warnings"]]  # type: ignore[index, union-attr]
    assert "unmapped_source_fields_ignored" in codes


def test_mapped_parquet_with_a_non_canonical_timestamp_column(tmp_path: Path) -> None:
    # Arrange: convert the CSV export to Parquet with a timezone-aware started_at column.
    pyarrow = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    with (FIXTURES / "mapped_export.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    columns = {name: [row[name] or None for row in rows] for name in rows[0]}
    columns["started_at"] = [
        datetime.fromisoformat(value.replace("Z", "+00:00")) for value in columns["started_at"]
    ]
    table = pyarrow.table(
        {
            **{name: pyarrow.array(values) for name, values in columns.items()},
            "started_at": pyarrow.array(columns["started_at"], pyarrow.timestamp("us", tz="UTC")),
            "latency_s": pyarrow.array([float(value) for value in columns["latency_s"]]),
        }
    )
    path = tmp_path / "export.parquet"
    parquet.write_table(table, path)

    # Act
    dataset = validate_file(path, mapping=FIXTURES / "mapped_export.csv.mapping.toml")

    # Assert
    assert serialize_normalized_jsonl(dataset) == _canonical_events()


def test_canonical_readers_still_require_canonical_columns(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "export.csv"
    path.write_text("session_id,metadata.environment\nsession-1,prod\n", encoding="utf-8")

    # Act / Assert
    with pytest.raises(FormatError, match="missing_csv_columns"):
        validate_file(path)


def test_mapped_csv_keeps_metadata_prefixed_columns_as_plain_columns(tmp_path: Path) -> None:
    # Arrange: a column literally named metadata.environment is addressed by its full name.
    path = tmp_path / "export.csv"
    path.write_text(
        "t,s,at,kind,name,ms,state,done,metadata.environment\n"
        "trace-1,step-1,2026-09-21T10:00:00Z,tool,search,5,ok,success,prod\n",
        encoding="utf-8",
    )
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        'mapping_version = "1"\n[fields]\ntrace_id = "t"\nstep_id = "s"\ntimestamp = "at"\n'
        'operation_type = "kind"\ncomponent = "name"\nduration_ms = "ms"\nstatus = "state"\n'
        'outcome = "done"\n[metadata]\nenvironment = "metadata.environment"\n',
        encoding="utf-8",
    )

    # Act
    dataset = validate_file(path, mapping=mapping)

    # Assert
    assert dict(dataset.events[0].metadata) == {"environment": "prod"}
    assert dataset.warnings == ()


@pytest.mark.parametrize("input_format", ["otlp-json", "otlp-jsonl"])
def test_mappings_are_rejected_for_otlp_inputs(input_format: str) -> None:
    with pytest.raises(UsageError, match="OTLP"):
        validate_file(
            FIXTURES / "otlp_trace.json",
            input_format=input_format,
            mapping=FIXTURES / "mapped_export.mapping.toml",
        )


def test_mapped_parquet_keeps_nanosecond_timestamps_and_rejects_naive_ones(
    tmp_path: Path,
) -> None:
    # Arrange: one aware nanosecond column and one naive column.
    pyarrow = pytest.importorskip("pyarrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    columns = {
        "t": ["trace-1"],
        "s": ["step-1"],
        "kind": ["tool"],
        "name": ["search"],
        "ms": [5],
        "state": ["ok"],
        "done": ["success"],
    }
    aware = pyarrow.array([1_790_000_000_000_000_001], pyarrow.timestamp("ns", tz="+03:00"))
    naive = pyarrow.array([1_790_000_000_000_000], pyarrow.timestamp("us"))
    path = tmp_path / "export.parquet"
    parquet.write_table(pyarrow.table({**columns, "at": aware, "local": naive}), path)
    mapping = (
        'mapping_version = "1"\n[fields]\ntrace_id = "t"\nstep_id = "s"\n'
        'operation_type = "kind"\ncomponent = "name"\nduration_ms = "ms"\nstatus = "state"\n'
        'outcome = "done"\n'
    )
    aware_mapping = tmp_path / "aware.toml"
    aware_mapping.write_text(mapping + 'timestamp = "at"\n', encoding="utf-8")
    naive_mapping = tmp_path / "naive.toml"
    naive_mapping.write_text(mapping + 'timestamp = "local"\n', encoding="utf-8")

    # Act
    dataset = validate_file(path, mapping=aware_mapping)

    # Assert
    assert dataset.events[0].timestamp_ns == 1_790_000_000_000_000_001
    assert '"timestamp":"2026-09-21T14:13:20.000000001Z"' in serialize_normalized_jsonl(dataset)
    with pytest.raises(ValidationError, match="invalid_timestamp"):
        validate_file(path, mapping=naive_mapping)
