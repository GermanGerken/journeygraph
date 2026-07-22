"""Generic JSONL, CSV, optional Parquet, and OTLP/JSON readers."""

from __future__ import annotations

import csv
import importlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from journeygraph.domain.models import SourceRecord
from journeygraph.exceptions import FileOperationError, FormatError
from journeygraph.ingestion.otlp import read_otlp_json

SUPPORTED_FORMATS = ("jsonl", "csv", "parquet", "otlp-json")
_PARQUET_TIMESTAMP_NS_FACTORS = {
    "s": 1_000_000_000,
    "ms": 1_000_000,
    "us": 1_000,
    "ns": 1,
}


def detect_format(path: Path) -> str:
    """Detect only unambiguous generic formats; OTLP JSON remains explicit."""

    suffix = path.suffix.casefold()
    if suffix in {".jsonl", ".ndjson"}:
        return "jsonl"
    if suffix == ".csv":
        return "csv"
    if suffix in {".parquet", ".pq"}:
        return "parquet"
    raise FormatError(
        f"cannot infer input format from {path.name!r}. "
        "Fix: use --format jsonl, csv, parquet, or explicit --format otlp-json"
    )


def read_records(path: str | Path, input_format: str = "auto") -> tuple[SourceRecord, ...]:
    """Decode a supported local file without applying canonical validation."""

    input_path = Path(path)
    selected = detect_format(input_path) if input_format == "auto" else input_format
    if selected not in SUPPORTED_FORMATS:
        raise FormatError(
            f"unsupported input format {selected!r}. "
            f"Fix: choose one of {', '.join(SUPPORTED_FORMATS)}"
        )
    if not input_path.exists():
        raise FileOperationError(f"input file does not exist: {input_path}")
    if not input_path.is_file():
        raise FileOperationError(f"input path is not a regular file: {input_path}")
    try:
        if selected == "jsonl":
            return _read_jsonl(input_path)
        if selected == "csv":
            return _read_csv(input_path)
        if selected == "parquet":
            return _read_parquet(input_path)
        return read_otlp_json(input_path)
    except csv.Error as error:
        raise FormatError(
            "[malformed_csv] input is not valid CSV. "
            "Fix: provide UTF-8 CSV with bounded fields and one record per row"
        ) from error
    except UnicodeError as error:
        raise FormatError(
            "[invalid_utf8] input is not valid UTF-8. "
            "Fix: encode textual JSONL, CSV, or OTLP/JSON input as UTF-8"
        ) from error
    except OSError as error:
        raise FileOperationError(
            f"cannot read input file {input_path}: {error.strerror or error}"
        ) from error


def _read_jsonl(path: Path) -> tuple[SourceRecord, ...]:
    records: list[SourceRecord] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise FormatError(
                    f"[malformed_jsonl] line {line_number}, column {error.colno}: "
                    "record is not valid JSON. Fix: write one complete JSON object per line"
                ) from error
            except ValueError as error:
                raise FormatError(
                    f"[invalid_json_value] line {line_number}: JSON value exceeds decoder limits. "
                    "Fix: use canonical bounded numeric values"
                ) from error
            if not isinstance(value, dict):
                raise FormatError(
                    f"[invalid_jsonl_record] line {line_number}: record is not an object. "
                    "Fix: write one journeygraph.event/v1 object per line"
                )
            records.append(
                SourceRecord(cast(dict[str, object], value), f"line {line_number}", len(records))
            )
    return tuple(records)


def _read_csv(path: Path) -> tuple[SourceRecord, ...]:
    records: list[SourceRecord] = []
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            return ()
        if any(not field for field in reader.fieldnames) or len(set(reader.fieldnames)) != len(
            reader.fieldnames
        ):
            raise FormatError(
                "[invalid_csv_header] header contains an empty or duplicate column. "
                "Fix: use one unique non-empty name for every column"
            )
        missing = sorted(
            {
                "schema_version",
                "trace_id",
                "step_id",
                "timestamp",
                "operation_type",
                "component",
                "duration_ms",
                "status",
            }
            - set(reader.fieldnames)
        )
        if missing:
            raise FormatError(
                f"[missing_csv_columns] header: missing required columns {', '.join(missing)}. "
                "Fix: add every journeygraph.event/v1 required column"
            )
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise FormatError(
                    f"[extra_csv_values] row {row_number}: row has more values than the header. "
                    "Fix: add named columns or remove the extra values"
                )
            data: dict[str, object] = {}
            metadata: dict[str, object] = {}
            for key, raw_value in row.items():
                if key is None:
                    continue
                value: object | None = raw_value
                if value == "":
                    value = None
                if key.startswith("metadata."):
                    metadata[key.removeprefix("metadata.")] = value
                else:
                    data[key] = value
            if metadata:
                data["metadata"] = metadata
            records.append(SourceRecord(data, f"row {row_number}", len(records)))
    return tuple(records)


def _read_parquet(path: Path) -> tuple[SourceRecord, ...]:
    try:
        pyarrow = importlib.import_module("pyarrow")
        parquet = importlib.import_module("pyarrow.parquet")
    except ModuleNotFoundError as error:
        raise FormatError(
            "[parquet_dependency_missing] Parquet support is not installed. "
            "Fix: install journeygraph[parquet]"
        ) from error
    try:
        table = parquet.read_table(path)
    except Exception as error:  # PyArrow exposes several version-specific decode exception types.
        raise FormatError(
            f"[malformed_parquet] file cannot be decoded as Parquet ({type(error).__name__}). "
            "Fix: provide a valid Parquet file using the canonical schema"
        ) from error
    try:
        column_names = tuple(table.column_names)
    except Exception as error:  # PyArrow schema errors vary by release and extension type.
        raise FormatError(
            f"[invalid_parquet_schema] schema cannot be inspected ({type(error).__name__}). "
            "Fix: provide a readable Parquet schema with canonical named columns"
        ) from error
    duplicates = sorted({name for name in column_names if column_names.count(name) > 1})
    if duplicates:
        raise FormatError(
            "[invalid_parquet_schema] schema contains duplicate column names. "
            "Fix: use one unique name for every canonical Parquet column"
        )
    required = frozenset(
        {
            "schema_version",
            "trace_id",
            "step_id",
            "timestamp",
            "operation_type",
            "component",
            "duration_ms",
            "status",
        }
    )
    missing = sorted(required - set(column_names))
    if missing:
        raise FormatError(
            f"[missing_parquet_columns] schema: missing required columns {', '.join(missing)}. "
            "Fix: add every journeygraph.event/v1 required column"
        )
    try:
        timestamp_index = column_names.index("timestamp")
        timestamp_type = table.schema.field(timestamp_index).type
        timestamp_ns: list[int | None]
        table_for_rows = table
        if pyarrow.types.is_timestamp(timestamp_type):
            factor = _PARQUET_TIMESTAMP_NS_FACTORS[timestamp_type.unit]
            raw_timestamps = table.column(timestamp_index).cast(pyarrow.int64()).to_pylist()
            timestamp_ns = [
                None if raw_timestamp is None else int(raw_timestamp) * factor
                for raw_timestamp in raw_timestamps
            ]
            microsecond_timestamps = [
                None if exact_ns is None else exact_ns // 1_000 for exact_ns in timestamp_ns
            ]
            python_timestamp_type = pyarrow.timestamp("us", tz=timestamp_type.tz)
            python_timestamps = pyarrow.array(
                microsecond_timestamps,
                type=python_timestamp_type,
            )
            table_for_rows = table.set_column(timestamp_index, "timestamp", python_timestamps)
        else:
            timestamp_ns = [None] * table.num_rows
        rows = cast(list[object], table_for_rows.to_pylist())
        if len(rows) != len(timestamp_ns):
            raise ValueError("Parquet row and timestamp counts differ")
        records: list[SourceRecord] = []
        for index, (row, exact_ns) in enumerate(zip(rows, timestamp_ns, strict=True), start=1):
            if not isinstance(row, Mapping):
                raise TypeError("converted Parquet row is not a mapping")
            records.append(
                SourceRecord(
                    cast(Mapping[str, object], row),
                    f"row {index}",
                    index - 1,
                    timestamp_ns=exact_ns,
                )
            )
    except Exception as error:  # PyArrow exposes version-specific conversion exception types.
        raise FormatError(
            f"[invalid_parquet_values] rows cannot be converted to canonical values "
            f"({type(error).__name__}). Fix: use canonical scalar values and a valid "
            "timezone-aware Arrow timestamp column"
        ) from error
    return tuple(records)
