from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests_functional.helpers import CommandResult, assert_no_traceback, read_jsonl


def _canonical_parquet_table(pyarrow: Any, timestamp: object) -> object:
    return pyarrow.table(
        {
            "schema_version": ["1.0"],
            "trace_id": ["trace-parquet-nanoseconds"],
            "step_id": ["step-1"],
            "timestamp": timestamp,
            "operation_type": ["request"],
            "component": ["Parquet CLI"],
            "duration_ms": [1],
            "status": ["ok"],
            "outcome": ["success"],
        }
    )


def test_validate_parquet_preserves_submicrosecond_timestamp_in_normalized_output(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange
    pyarrow = pytest.importorskip("pyarrow", reason="Parquet support is optional")
    parquet = pytest.importorskip("pyarrow.parquet", reason="Parquet support is optional")
    input_path = tmp_path / "nanoseconds.parquet"
    normalized_path = tmp_path / "normalized.jsonl"
    timestamp = pyarrow.array(
        [1_767_225_600_123_456_789],
        type=pyarrow.timestamp("ns", tz="Asia/Kolkata"),
    )
    parquet.write_table(_canonical_parquet_table(pyarrow, timestamp), input_path)

    # Act
    result = cli(
        "validate",
        input_path,
        "--format",
        "parquet",
        "--normalized-out",
        normalized_path,
    )

    # Assert
    result.assert_exit(0)
    assert not result.stderr.strip(), result.stderr
    assert read_jsonl(normalized_path)[0]["timestamp"] == "2026-01-01T00:00:00.123456789Z"


def test_validate_parquet_wrong_schema_is_an_actionable_format_error(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange
    pyarrow = pytest.importorskip("pyarrow", reason="Parquet support is optional")
    parquet = pytest.importorskip("pyarrow.parquet", reason="Parquet support is optional")
    input_path = tmp_path / "wrong-schema.parquet"
    normalized_path = tmp_path / "wrong-schema-normalized.jsonl"
    parquet.write_table(pyarrow.table({"unexpected": ["value"]}), input_path)

    # Act
    result = cli(
        "validate",
        input_path,
        "--format",
        "parquet",
        "--normalized-out",
        normalized_path,
    )

    # Assert
    result.assert_exit(2)
    assert not result.stdout.strip()
    assert_no_traceback(result)
    assert "[missing_parquet_columns]" in result.stderr
    assert "schema_version" in result.stderr
    assert "Fix:" in result.stderr
    assert not normalized_path.exists()


def test_validate_parquet_row_conversion_error_is_not_an_internal_failure(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange
    pyarrow = pytest.importorskip("pyarrow", reason="Parquet support is optional")
    parquet = pytest.importorskip("pyarrow.parquet", reason="Parquet support is optional")
    input_path = tmp_path / "invalid-timezone.parquet"
    normalized_path = tmp_path / "invalid-timezone-normalized.jsonl"
    timestamp = pyarrow.array(
        [1_767_225_600_000_000_123],
        type=pyarrow.timestamp("ns", tz="Mars/Olympus"),
    )
    parquet.write_table(_canonical_parquet_table(pyarrow, timestamp), input_path)

    # Act
    result = cli(
        "validate",
        input_path,
        "--format",
        "parquet",
        "--normalized-out",
        normalized_path,
    )

    # Assert
    result.assert_exit(2)
    assert not result.stdout.strip()
    assert_no_traceback(result)
    assert "[invalid_parquet_values]" in result.stderr
    assert "row" in result.stderr.lower()
    assert "Fix:" in result.stderr
    assert not normalized_path.exists()
