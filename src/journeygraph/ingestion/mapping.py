"""Declarative TOML field mapping from arbitrary source records to canonical events.

A mapping names, for each canonical field, the dotted path of the source value to read.  Only
mapped paths are copied; every other source field is ignored and counted, never emitted.
The module evaluates no code and makes no network calls.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from journeygraph.domain.models import Issue, SourceRecord, datetime_to_unix_ns
from journeygraph.exceptions import FileOperationError, UsageError, ValidationError

MAPPING_VERSION = "1"
_REQUIRED = (
    "trace_id",
    "step_id",
    "timestamp",
    "operation_type",
    "component",
    "duration_ms",
    "status",
)
_OPTIONAL = ("parent_step_id", "outcome", "input_tokens", "output_tokens", "cost_usd")
_FIELDS = (*_REQUIRED, *_OPTIONAL)
_VALUE_MAP_FIELDS = ("status", "outcome", "operation_type")
_TABLES = frozenset(
    {"mapping_version", "fields", "constants", "values", "metadata", "timestamp", "duration"}
)
_TIMESTAMP_FACTORS = {
    "iso8601": None,
    "utc_naive": 0,
    "unix_s": 1_000_000_000,
    "unix_ms": 1_000_000,
    "unix_us": 1_000,
    "unix_ns": 1,
}
_DURATION_FACTORS = {
    "ms": Decimal(1),
    "s": Decimal(1000),
    "us": Decimal("0.001"),
    "ns": Decimal("0.000001"),
}
_NS_PER_MS = Decimal(1_000_000)
_UTC_NAIVE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[ T](?P<time>\d{2}:\d{2}:\d{2})(?:\.(?P<fraction>\d{1,9}))?$"
)
_ISO = re.compile(r"^(?P<base>[^.]+?)(?:\.(?P<fraction>\d{1,9}))?(?P<offset>Z|[+-]\d{2}:\d{2})$")


class MappingError(ValueError):
    """A mapping document is malformed."""


@dataclass(frozen=True, slots=True)
class SourcePath:
    """A dotted source path, kept both as written and as segments."""

    text: str
    segments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FieldMapping:
    """A validated mapping document."""

    fields: Mapping[str, SourcePath]
    constants: Mapping[str, str | int | float]
    values: Mapping[str, Mapping[str, str]]
    metadata: Mapping[str, SourcePath]
    timestamp_unit: str = "iso8601"
    duration_field: SourcePath | None = None
    duration_unit: str = "ms"
    duration_start: SourcePath | None = None
    duration_end: SourcePath | None = None


@dataclass(frozen=True, slots=True)
class MappedRecords:
    """Canonical records built from a mapping and the count of ignored source paths."""

    records: tuple[SourceRecord, ...]
    ignored_path_count: int
    used_paths: frozenset[tuple[str, ...]] = field(default_factory=frozenset)


def parse_path(text: str) -> SourcePath:
    """Parse ``a.b."c.d"`` into ``("a", "b", "c.d")``."""

    segments: list[str] = []
    current: list[str] = []
    quoted = False
    closed = False
    for character in text:
        if quoted:
            if character == '"':
                quoted, closed = False, True
            else:
                current.append(character)
        elif character == '"':
            if current or closed:
                raise MappingError(f"source path {text!r} has a misplaced quote")
            quoted = True
        elif character == ".":
            if not current and not closed:
                raise MappingError(f"source path {text!r} has an empty segment")
            segments.append("".join(current))
            current, closed = [], False
        else:
            if closed:
                raise MappingError(f"source path {text!r} has text after a closing quote")
            current.append(character)
    if quoted:
        raise MappingError(f"source path {text!r} has an unterminated quote")
    if not current and not closed:
        raise MappingError(f"source path {text!r} has an empty segment")
    segments.append("".join(current))
    return SourcePath(text, tuple(segments))


def _table(document: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = document.get(name, {})
    if not isinstance(value, dict):
        raise MappingError(f"{name} must be a table")
    return value


def _path_table(document: Mapping[str, object], name: str) -> dict[str, SourcePath]:
    result: dict[str, SourcePath] = {}
    for key, value in _table(document, name).items():
        if not isinstance(value, str) or not value:
            raise MappingError(f"{name}.{key} must be a non-empty source path string")
        result[key] = parse_path(value)
    return result


def parse_mapping(text: str) -> FieldMapping:
    """Parse and validate a TOML mapping document."""

    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise MappingError(f"invalid TOML: {error}") from None
    unknown = sorted(set(document) - _TABLES)
    if unknown:
        raise MappingError(f"unknown key(s): {', '.join(unknown)}")
    if document.get("mapping_version") != MAPPING_VERSION:
        raise MappingError(f'mapping_version must be "{MAPPING_VERSION}"')

    fields = _path_table(document, "fields")
    constants: dict[str, str | int | float] = {}
    for key, value in _table(document, "constants").items():
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise MappingError(f"constants.{key} must be a string or number")
        constants[key] = value
    metadata = _path_table(document, "metadata")
    for key in metadata:
        if not key.strip():
            raise MappingError("metadata keys must be non-empty")

    unknown_fields = sorted((set(fields) | set(constants)) - set(_FIELDS))
    if unknown_fields:
        raise MappingError(f"unknown canonical field(s): {', '.join(unknown_fields)}")
    both = sorted(set(fields) & set(constants))
    if both:
        raise MappingError(f"field(s) both mapped and constant: {', '.join(both)}")

    values: dict[str, dict[str, str]] = {}
    for name, table in _table(document, "values").items():
        if name not in _VALUE_MAP_FIELDS:
            raise MappingError(
                f"values.{name} is not supported; use status, outcome, or operation_type"
            )
        if not isinstance(table, dict):
            raise MappingError(f"values.{name} must be a table")
        for source, target in table.items():
            if not isinstance(target, str):
                raise MappingError(f"values.{name}.{source} must be a string")
        values[name] = dict(table)

    timestamp = _table(document, "timestamp")
    if set(timestamp) - {"unit"}:
        raise MappingError("timestamp accepts only unit")
    timestamp_unit = timestamp.get("unit", "iso8601")
    if timestamp_unit not in _TIMESTAMP_FACTORS:
        raise MappingError(f"timestamp.unit must be one of {', '.join(_TIMESTAMP_FACTORS)}")

    duration = _table(document, "duration")
    if set(duration) - {"field", "unit", "start", "end"}:
        raise MappingError("duration accepts only field and unit, or start and end")
    duration_field = duration_start = duration_end = None
    duration_unit = duration.get("unit", "ms")
    if duration:
        if "duration_ms" in fields or "duration_ms" in constants:
            raise MappingError("use either [duration] or fields.duration_ms, not both")
        paths = {
            key: parse_path(value) if isinstance(value, str) and value else None
            for key, value in duration.items()
            if key != "unit"
        }
        if any(path is None for path in paths.values()):
            raise MappingError("duration paths must be non-empty strings")
        if set(paths) == {"field"}:
            duration_field = paths["field"]
            if duration_unit not in _DURATION_FACTORS:
                raise MappingError(f"duration.unit must be one of {', '.join(_DURATION_FACTORS)}")
        elif set(paths) == {"start", "end"} and "unit" not in duration:
            duration_start, duration_end = paths["start"], paths["end"]
        else:
            raise MappingError("duration needs field (with optional unit) or start and end")

    covered = set(fields) | set(constants)
    if duration:
        covered.add("duration_ms")
    missing = [name for name in _REQUIRED if name not in covered]
    if missing:
        raise MappingError(f"required field(s) not mapped: {', '.join(missing)}")
    if "timestamp" in constants:
        raise MappingError("timestamp cannot be a constant")
    return FieldMapping(
        fields=fields,
        constants=constants,
        values=values,
        metadata=metadata,
        timestamp_unit=str(timestamp_unit),
        duration_field=duration_field,
        duration_unit=str(duration_unit),
        duration_start=duration_start,
        duration_end=duration_end,
    )


def load_mapping(path: str | Path) -> FieldMapping:
    """Read and validate a mapping file, mapping failures to CLI exit codes."""

    mapping_path = Path(path)
    try:
        text = mapping_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise UsageError(f"invalid mapping file {mapping_path}: not UTF-8") from error
    except OSError as error:
        raise FileOperationError(
            f"cannot read mapping file {mapping_path}: {error.strerror or error}"
        ) from error
    try:
        return parse_mapping(text)
    except MappingError as error:
        raise UsageError(f"invalid mapping file {mapping_path}: {error}") from error


_MISSING = object()


def _lookup(data: Mapping[str, object], path: SourcePath) -> tuple[object, tuple[str, ...]]:
    if path.text in data:
        return data[path.text], (path.text,)
    value: object = data
    for segment in path.segments:
        if not isinstance(value, Mapping) or segment not in value:
            return _MISSING, path.segments
        value = value[segment]
    return value, path.segments


def _leaf_paths(value: object, prefix: tuple[str, ...] = ()) -> Iterable[tuple[str, ...]]:
    if isinstance(value, Mapping) and (value or not prefix):
        for key, child in value.items():
            yield from _leaf_paths(child, (*prefix, str(key)))
    else:
        yield prefix


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, float):
            parsed = Decimal(repr(value))
        elif isinstance(value, (int, Decimal)):
            parsed = Decimal(value)
        elif isinstance(value, str):
            parsed = Decimal(value.strip())
        else:
            return None
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _plain(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


def _iso_to_ns(value: object) -> int | None:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return datetime_to_unix_ns(value.astimezone(UTC))
    if not isinstance(value, str):
        return None
    match = _ISO.fullmatch(value.strip())
    if match is None:
        return None
    offset = match.group("offset")
    try:
        parsed = datetime.fromisoformat(
            match.group("base") + ("+00:00" if offset == "Z" else offset)
        )
    except ValueError:
        return None
    delta = parsed - datetime(1970, 1, 1, tzinfo=UTC)
    fraction = (match.group("fraction") or "").ljust(9, "0")
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + int(fraction)


def _naive_to_ns(value: object) -> int | None:
    """Read ``YYYY-MM-DD[ T]HH:MM:SS[.fraction]`` without an offset as UTC."""

    if not isinstance(value, str):
        return None
    match = _UTC_NAIVE.fullmatch(value.strip())
    if match is None:
        return None
    try:
        parsed = datetime.fromisoformat(f"{match.group('date')}T{match.group('time')}+00:00")
    except ValueError:
        return None
    delta = parsed - datetime(1970, 1, 1, tzinfo=UTC)
    fraction = (match.group("fraction") or "").ljust(9, "0")
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + int(fraction)


def _instant(value: object, unit: str) -> int | None:
    factor = _TIMESTAMP_FACTORS[unit]
    if factor is None:
        return _iso_to_ns(value)
    if factor == 0:
        return _naive_to_ns(value)
    return _unix_to_ns(value, factor)


def _unix_to_ns(value: object, factor: int) -> int | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    scaled = parsed * factor
    if scaled != scaled.to_integral_value():
        return None
    return int(scaled)


def _ns_to_rfc3339(timestamp_ns: int) -> str | None:
    seconds, nanoseconds = divmod(timestamp_ns, 1_000_000_000)
    try:
        moment = datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return f"{moment.replace(tzinfo=None).isoformat(timespec='seconds')}.{nanoseconds:09d}Z"


def _error(location: str, field_name: str, path: str, message: str, hint: str) -> Issue:
    return Issue(
        "error",
        "mapped_value_invalid",
        f"{location}.{field_name}",
        f"source path {path!r} {message}",
        hint,
    )


class _RecordMapper:
    def __init__(self, mapping: FieldMapping) -> None:
        self.mapping = mapping
        self.errors: list[Issue] = []
        self.used: set[tuple[str, ...]] = set()

    def _read(self, record: SourceRecord, path: SourcePath) -> object:
        value, used = _lookup(record.data, path)
        self.used.add(used)
        return value

    def _timestamp(
        self, record: SourceRecord, value: object, path: str
    ) -> tuple[object, int | None]:
        unit = self.mapping.timestamp_unit
        if _TIMESTAMP_FACTORS[unit] is None:
            return value, None
        timestamp_ns = _instant(value, unit)
        text = None if timestamp_ns is None else _ns_to_rfc3339(timestamp_ns)
        if text is None:
            self.errors.append(
                _error(
                    record.location,
                    "timestamp",
                    path,
                    f"is not a valid {unit} timestamp in range",
                    "map a value in the timestamp unit or change timestamp.unit",
                )
            )
            return None, None
        return text, timestamp_ns

    def _instant_ns(self, record: SourceRecord, path: SourcePath) -> int | None:
        return _instant(self._read(record, path), self.mapping.timestamp_unit)

    def _duration_pair(self, record: SourceRecord, start: SourcePath, end: SourcePath) -> object:
        start_ns = self._instant_ns(record, start)
        end_ns = self._instant_ns(record, end)
        if start_ns is None or end_ns is None:
            self.errors.append(
                _error(
                    record.location,
                    "duration_ms",
                    f"{start.text} / {end.text}",
                    f"must both be {self.mapping.timestamp_unit} instants",
                    "map start and end values in the timestamp unit",
                )
            )
            return _MISSING
        return _plain(Decimal(end_ns - start_ns) / _NS_PER_MS)

    def _duration_value(self, record: SourceRecord, path: SourcePath) -> object:
        mapping = self.mapping
        value = self._read(record, path)
        if value is _MISSING or value is None or mapping.duration_unit == "ms":
            return value
        parsed = _decimal(value)
        if parsed is None:
            self.errors.append(
                _error(
                    record.location,
                    "duration_ms",
                    path.text,
                    "is not numeric",
                    "map a numeric duration or remove duration.unit",
                )
            )
            return _MISSING
        return _plain(parsed * _DURATION_FACTORS[mapping.duration_unit])

    def map(self, record: SourceRecord) -> SourceRecord:
        mapping = self.mapping
        data: dict[str, object] = {"schema_version": "1.0"}
        data.update(mapping.constants)
        timestamp_ns: int | None = None
        for name, path in mapping.fields.items():
            value = self._read(record, path)
            if value is _MISSING:
                if name in _REQUIRED:
                    self.errors.append(
                        Issue(
                            "error",
                            "mapped_field_missing",
                            f"{record.location}.{name}",
                            f"required field {name} is missing at source path {path.text!r}",
                            "add the source value or map the field to another path",
                        )
                    )
                continue
            if name == "timestamp":
                value, timestamp_ns = self._timestamp(record, value, path.text)
            data[name] = value
        duration: object = _MISSING
        if mapping.duration_start is not None and mapping.duration_end is not None:
            duration = self._duration_pair(record, mapping.duration_start, mapping.duration_end)
        elif mapping.duration_field is not None:
            duration = self._duration_value(record, mapping.duration_field)
        if duration is not _MISSING:
            data["duration_ms"] = duration
        for name, table in mapping.values.items():
            value = data.get(name)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                data[name] = table.get(str(value), value)
        metadata: dict[str, object] = {}
        for key, path in mapping.metadata.items():
            value = self._read(record, path)
            if value is not _MISSING:
                metadata[key] = value
        if metadata:
            data["metadata"] = metadata
        return SourceRecord(data, record.location, record.sequence, timestamp_ns=timestamp_ns)


def apply_mapping(records: Sequence[SourceRecord], mapping: FieldMapping) -> MappedRecords:
    """Build canonical records; raise one ``ValidationError`` for every mapping failure."""

    mapper = _RecordMapper(mapping)
    mapped = tuple(mapper.map(record) for record in records)
    if mapper.errors:
        raise ValidationError(sorted(mapper.errors, key=lambda issue: (issue.location, issue.code)))
    used = frozenset(mapper.used)
    ignored = {
        leaf
        for record in records
        for leaf in _leaf_paths(record.data)
        if leaf and not any(leaf[: len(prefix)] == prefix for prefix in used)
    }
    return MappedRecords(mapped, len(ignored), used)


def ignored_fields_warning(count: int) -> Issue:
    """Return the dataset warning for source paths a mapping did not read."""

    return Issue(
        "warning",
        "unmapped_source_fields_ignored",
        "input",
        f"{count} distinct source field path(s) were not mapped and were ignored.",
        "map a path explicitly if the field is needed; ignored fields never reach outputs",
    )
