"""Canonical validation and deterministic trace normalization."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import cast

from journeygraph.domain.models import (
    CanonicalEvent,
    Issue,
    NormalizedDataset,
    Outcome,
    SourceRecord,
    Status,
    Trace,
    datetime_to_unix_ns,
)
from journeygraph.exceptions import ValidationError
from journeygraph.normalization.privacy import (
    DEFAULT_METADATA_ALLOWLIST,
    filter_metadata,
    is_safe_unicode_text,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OPERATION_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_ISO_TIMESTAMP = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,9}))?(?P<offset>Z|[+-]\d{2}:\d{2})$"
)
_KNOWN_OPERATION_TYPES = frozenset(
    {
        "agent",
        "chain",
        "client",
        "consumer",
        "embedding",
        "evaluator",
        "guardrail",
        "handoff",
        "internal",
        "llm",
        "model",
        "outcome",
        "producer",
        "prompt",
        "request",
        "reranker",
        "retrieval",
        "retriever",
        "router",
        "server",
        "span",
        "tool",
        "unspecified",
        "validation",
    }
)
_REQUIRED_FIELDS = frozenset(
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
_KNOWN_FIELDS = _REQUIRED_FIELDS | {
    "parent_step_id",
    "outcome",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "metadata",
}
_OUTCOMES = frozenset({"success", "failure", "handoff", "dropoff", "unknown"})
_STATUSES = frozenset({"unset", "ok", "error"})
_MAX_NUMERIC_VALUE = Decimal("1000000000000000")
_MAX_SIGNIFICANT_DIGITS = 15


def _error(code: str, location: str, message: str, hint: str) -> Issue:
    return Issue("error", code, location, message, hint)


def _warning(code: str, location: str, message: str, hint: str) -> Issue:
    return Issue("warning", code, location, message, hint)


def _parse_identifier(
    value: object, *, field: str, location: str, required: bool = True
) -> tuple[str | None, Issue | None]:
    if value is None or value == "":
        if not required:
            return None, None
        return None, _error(
            "missing_identifier",
            f"{location}.{field}",
            f"required identifier {field} is missing",
            "provide 1-128 letters, digits, dots, underscores, colons, or hyphens",
        )
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        return None, _error(
            "invalid_identifier",
            f"{location}.{field}",
            f"{field} is not a valid identifier",
            "use 1-128 letters, digits, dots, underscores, colons, or hyphens",
        )
    return value, None


def _parse_timestamp(
    value: object, *, location: str, exact_ns: int | None
) -> tuple[datetime | None, int | None, Issue | None]:
    field_location = f"{location}.timestamp"
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return (
                None,
                None,
                _error(
                    "invalid_timestamp",
                    field_location,
                    "timestamp datetime has no UTC offset",
                    "store a timezone-aware Parquet timestamp or an RFC 3339 string",
                ),
            )
        parsed_datetime = value.astimezone(UTC)
        if exact_ns is None:
            exact_ns = datetime_to_unix_ns(parsed_datetime)
        return parsed_datetime, exact_ns, None
    if not isinstance(value, str):
        return (
            None,
            None,
            _error(
                "invalid_timestamp",
                field_location,
                "timestamp must be an RFC 3339 string with an explicit offset",
                "use a value such as 2026-01-02T03:04:05.000000Z",
            ),
        )
    match = _ISO_TIMESTAMP.fullmatch(value)
    if match is None:
        return (
            None,
            None,
            _error(
                "invalid_timestamp",
                field_location,
                "timestamp is not RFC 3339 with an explicit UTC offset",
                "use YYYY-MM-DDTHH:MM:SS[.fraction]Z or an explicit ±HH:MM offset",
            ),
        )
    parse_value = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(parse_value).astimezone(UTC)
    except ValueError:
        return (
            None,
            None,
            _error(
                "invalid_timestamp",
                field_location,
                "timestamp contains an invalid calendar or offset value",
                "provide a real calendar time with a valid UTC offset",
            ),
        )
    if exact_ns is None:
        whole_seconds = datetime_to_unix_ns(parsed.replace(microsecond=0)) // 1_000_000_000
        fraction = (match.group("fraction") or "").ljust(9, "0")[:9]
        exact_ns = whole_seconds * 1_000_000_000 + int(fraction or "0")
    return parsed, exact_ns, None


def _parse_decimal(
    value: object,
    *,
    field: str,
    location: str,
    required: bool,
) -> tuple[Decimal | None, Issue | None]:
    field_location = f"{location}.{field}"
    if value is None or value == "":
        if required:
            return None, _error(
                "missing_numeric_value",
                field_location,
                f"required numeric field {field} is missing",
                "provide a finite non-negative number",
            )
        return None, None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None, _error(
            "invalid_numeric_value",
            field_location,
            f"{field} is not numeric",
            "provide a finite non-negative number",
        )
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        parsed = Decimal("NaN")
    if not parsed.is_finite() or parsed < 0:
        return None, _error(
            "invalid_numeric_value",
            field_location,
            f"{field} must be finite and non-negative",
            "replace NaN, infinity, or negative values with a finite non-negative number",
        )
    if parsed > _MAX_NUMERIC_VALUE:
        return None, _error(
            "numeric_value_out_of_range",
            field_location,
            f"{field} exceeds the supported maximum",
            "use a value no greater than 1000000000000000",
        )
    normalized = parsed.normalize()
    significant_digits = len(normalized.as_tuple().digits)
    if parsed != parsed.to_integral_value():
        converted = float(parsed)
        if (
            significant_digits > _MAX_SIGNIFICANT_DIGITS
            or not math.isfinite(converted)
            or Decimal(str(converted)) != parsed
        ):
            return None, _error(
                "numeric_precision_unsupported",
                field_location,
                f"{field} has more precision than the canonical JSON number contract",
                "use at most 15 significant decimal digits in an ordinary JSON number range",
            )
    return parsed, None


def _parse_integer(value: object, *, field: str, location: str) -> tuple[int | None, Issue | None]:
    parsed, issue = _parse_decimal(value, field=field, location=location, required=False)
    if issue is not None or parsed is None:
        return None, issue
    if parsed != parsed.to_integral_value():
        return None, _error(
            "invalid_integer_value",
            f"{location}.{field}",
            f"{field} must be a whole number",
            "provide a non-negative integer",
        )
    return int(parsed), None


def _parse_event(
    record: SourceRecord, *, allowed_metadata_keys: frozenset[str]
) -> tuple[CanonicalEvent | None, list[Issue], list[Issue]]:
    data = record.data
    errors: list[Issue] = []
    warnings: list[Issue] = []
    location = record.location

    errors.extend(
        [
            _error(
                "missing_required_field",
                f"{location}.{field}",
                f"required field {field} is missing",
                "add the field using the journeygraph.event/v1 schema",
            )
            for field in sorted(_REQUIRED_FIELDS - data.keys())
        ]
    )
    schema_version = data.get("schema_version")
    if schema_version is None or str(schema_version) != "1.0":
        errors.append(
            _error(
                "unsupported_schema_version",
                f"{location}.schema_version",
                "schema_version is not supported",
                "set schema_version to 1.0",
            )
        )

    trace_id, trace_issue = _parse_identifier(
        data.get("trace_id"), field="trace_id", location=location
    )
    step_id, step_issue = _parse_identifier(data.get("step_id"), field="step_id", location=location)
    parent_step_id, parent_issue = _parse_identifier(
        data.get("parent_step_id"),
        field="parent_step_id",
        location=location,
        required=False,
    )
    errors.extend(issue for issue in (trace_issue, step_issue, parent_issue) if issue is not None)

    timestamp, timestamp_ns, timestamp_issue = _parse_timestamp(
        data.get("timestamp"), location=location, exact_ns=record.timestamp_ns
    )
    if timestamp_issue is not None:
        errors.append(timestamp_issue)

    operation_value = data.get("operation_type")
    operation_type: str | None = None
    if not isinstance(operation_value, str) or _OPERATION_TYPE.fullmatch(operation_value) is None:
        errors.append(
            _error(
                "invalid_operation_type",
                f"{location}.operation_type",
                "operation_type is not a valid category",
                "use 1-64 letters, digits, dots, underscores, or hyphens, starting with a letter",
            )
        )
    else:
        operation_type = operation_value.casefold()
        if operation_type not in _KNOWN_OPERATION_TYPES:
            warnings.append(
                _warning(
                    "unknown_operation_type",
                    f"{location}.operation_type",
                    "an unknown but valid operation type was preserved",
                    "use a documented type or keep this custom type intentionally",
                )
            )

    component_value = data.get("component")
    component: str | None = None
    if not isinstance(component_value, str) or not component_value.strip():
        errors.append(
            _error(
                "invalid_component",
                f"{location}.component",
                "component must be a non-empty operational label",
                "provide a short tool, model, service, or step name",
            )
        )
    elif len(component_value.strip()) > 256:
        errors.append(
            _error(
                "invalid_component",
                f"{location}.component",
                "component exceeds 256 characters",
                "use a concise operational label and keep content out of component names",
            )
        )
    elif not is_safe_unicode_text(component_value.strip()):
        errors.append(
            _error(
                "invalid_component",
                f"{location}.component",
                "component contains invalid Unicode or XML control characters",
                "use ordinary Unicode text without control characters or surrogate code points",
            )
        )
    else:
        component = component_value.strip()

    duration_ms, duration_issue = _parse_decimal(
        data.get("duration_ms"), field="duration_ms", location=location, required=True
    )
    cost_usd, cost_issue = _parse_decimal(
        data.get("cost_usd"), field="cost_usd", location=location, required=False
    )
    input_tokens, input_issue = _parse_integer(
        data.get("input_tokens"), field="input_tokens", location=location
    )
    output_tokens, output_issue = _parse_integer(
        data.get("output_tokens"), field="output_tokens", location=location
    )
    errors.extend(
        issue
        for issue in (duration_issue, cost_issue, input_issue, output_issue)
        if issue is not None
    )

    status_value = data.get("status")
    status: Status | None = None
    if not isinstance(status_value, str) or status_value.casefold() not in _STATUSES:
        errors.append(
            _error(
                "invalid_status",
                f"{location}.status",
                "status must be unset, ok, or error",
                "use one of the documented lowercase status values",
            )
        )
    else:
        status = cast(Status, status_value.casefold())

    outcome_value = data.get("outcome")
    outcome: Outcome | None = None
    if outcome_value not in (None, ""):
        if not isinstance(outcome_value, str) or outcome_value.casefold() not in _OUTCOMES:
            errors.append(
                _error(
                    "invalid_outcome",
                    f"{location}.outcome",
                    "outcome is not one of the supported values",
                    "use success, failure, handoff, dropoff, unknown, or omit the field",
                )
            )
        else:
            outcome = cast(Outcome, outcome_value.casefold())

    metadata, metadata_warnings = filter_metadata(
        data.get("metadata"),
        allowed_keys=allowed_metadata_keys,
        location=f"{location}.metadata",
    )
    warnings.extend(metadata_warnings)
    warnings.extend(
        [
            _warning(
                "unknown_field_excluded",
                f"{location}.unknown[{field_index}]",
                "an unknown top-level field was excluded",
                "move safe operational values into allowlisted metadata or remove the field",
            )
            for field_index, _field in enumerate(sorted(data.keys() - _KNOWN_FIELDS), start=1)
        ]
    )

    if errors:
        return None, errors, warnings
    if (
        trace_id is None
        or step_id is None
        or timestamp is None
        or timestamp_ns is None
        or operation_type is None
        or component is None
        or duration_ms is None
        or status is None
    ):
        raise RuntimeError("normalization invariant failed after successful validation")
    return (
        CanonicalEvent(
            trace_id=trace_id,
            step_id=step_id,
            parent_step_id=parent_step_id,
            timestamp=timestamp,
            operation_type=operation_type,
            component=component,
            duration_ms=duration_ms,
            status=status,
            outcome=outcome,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            metadata=MappingProxyType(metadata),
            timestamp_ns=timestamp_ns,
        ),
        errors,
        warnings,
    )


def _find_parent_cycles(events: Sequence[CanonicalEvent]) -> list[tuple[str, ...]]:
    parent_by_id = {
        event.step_id: event.parent_step_id for event in events if event.parent_step_id is not None
    }
    cycles: set[tuple[str, ...]] = set()
    for start in sorted(parent_by_id):
        seen_at: dict[str, int] = {}
        path: list[str] = []
        current: str | None = start
        while current is not None and current in parent_by_id:
            if current in seen_at:
                cycle = path[seen_at[current] :]
                smallest = min(range(len(cycle)), key=cycle.__getitem__)
                canonical = tuple(cycle[smallest:] + cycle[:smallest])
                cycles.add(canonical)
                break
            seen_at[current] = len(path)
            path.append(current)
            current = parent_by_id.get(current)
    return sorted(cycles)


def _trace_relationship_issues(
    trace_id: str,
    events: Sequence[CanonicalEvent],
    all_step_traces: Mapping[str, frozenset[str]],
) -> tuple[list[Issue], list[Issue]]:
    warnings: list[Issue] = []
    errors: list[Issue] = []
    by_id = {event.step_id: event for event in events}
    roots = 0
    for event in events:
        parent_id = event.parent_step_id
        if parent_id is None:
            roots += 1
            continue
        parent = by_id.get(parent_id)
        if parent is None:
            roots += 1
            code = "cross_trace_parent" if parent_id in all_step_traces else "missing_parent"
            message = (
                "parent_step_id refers to a step in another trace"
                if code == "cross_trace_parent"
                else "parent_step_id does not exist in this trace"
            )
            warnings.append(
                _warning(
                    code,
                    f"trace[{trace_id}].step[{event.step_id}].parent_step_id",
                    message,
                    "provide a parent from the same trace or omit parent_step_id for a root",
                )
            )
        elif parent.sort_key > event.sort_key:
            warnings.append(
                _warning(
                    "parent_after_child",
                    f"trace[{trace_id}].step[{event.step_id}]",
                    "the recorded parent timestamp is later than its child",
                    "correct timestamps; chronological order is retained for analysis",
                )
            )
    if roots > 1:
        warnings.append(
            _warning(
                "disconnected_trace",
                f"trace[{trace_id}]",
                "the trace has multiple roots or disconnected parent relationships",
                "connect spans with same-trace parent_step_id values when available",
            )
        )
    errors.extend(
        [
            _error(
                "parent_cycle",
                f"trace[{trace_id}]",
                f"parent relationships contain a cycle across {len(cycle)} steps",
                "remove or correct a parent_step_id so the parent graph is acyclic",
            )
            for cycle in _find_parent_cycles(events)
        ]
    )
    return errors, warnings


def _make_trace(trace_id: str, events: Sequence[CanonicalEvent]) -> tuple[Trace, Issue | None]:
    explicit = [event.outcome for event in events if event.outcome is not None]
    if explicit:
        return Trace(trace_id, tuple(events), explicit[-1], "explicit"), None
    terminal = events[-1]
    if terminal.status == "error":
        return Trace(trace_id, tuple(events), "failure", "terminal_status"), _warning(
            "missing_outcome",
            f"trace[{trace_id}]",
            "the trace has no explicit outcome; terminal error was classified as failure",
            "set outcome on the terminal event when the business result is known",
        )
    return Trace(trace_id, tuple(events), "dropoff", "missing"), _warning(
        "missing_outcome",
        f"trace[{trace_id}]",
        "the trace has no explicit outcome and was classified as dropoff",
        "set outcome on the terminal event when the business result is known",
    )


def normalize_records(
    records: Iterable[SourceRecord],
    *,
    input_format: str,
    allow_metadata_keys: Iterable[str] = (),
    high_cardinality_threshold: int = 100,
) -> NormalizedDataset:
    """Validate decoded records and return a deterministic privacy-filtered dataset."""

    source_records = tuple(records)
    if not source_records:
        raise ValidationError(
            [
                _error(
                    "empty_input",
                    "input",
                    "the input contains no event records",
                    "provide at least one journeygraph.event/v1 record",
                )
            ]
        )
    allowed = frozenset(
        DEFAULT_METADATA_ALLOWLIST | {key.casefold() for key in allow_metadata_keys}
    )
    parsed: list[tuple[CanonicalEvent, SourceRecord]] = []
    errors: list[Issue] = []
    warnings: list[Issue] = []
    for record in source_records:
        event, event_errors, event_warnings = _parse_event(record, allowed_metadata_keys=allowed)
        errors.extend(event_errors)
        warnings.extend(event_warnings)
        if event is not None:
            parsed.append((event, record))
    if errors:
        raise ValidationError(sorted(errors, key=_issue_sort_key))

    unique: dict[tuple[str, str], CanonicalEvent] = {}
    for event, _record in parsed:
        identity = (event.trace_id, event.step_id)
        previous = unique.get(identity)
        if previous is None:
            unique[identity] = event
        elif previous == event:
            warnings.append(
                _warning(
                    "duplicate_event_removed",
                    f"trace[{event.trace_id}].step[{event.step_id}]",
                    "an exact duplicate event was removed",
                    "deduplicate exporter output to avoid this warning",
                )
            )
        else:
            errors.append(
                _error(
                    "conflicting_duplicate_event",
                    f"trace[{event.trace_id}].step[{event.step_id}]",
                    "events sharing trace_id and step_id contain conflicting values",
                    "assign a unique step_id or make duplicate records byte-equivalent in meaning",
                )
            )
    if errors:
        raise ValidationError(sorted(errors, key=_issue_sort_key))

    grouped: dict[str, list[CanonicalEvent]] = defaultdict(list)
    input_order: dict[str, list[str]] = defaultdict(list)
    for event, _record in parsed:
        if (
            unique.get((event.trace_id, event.step_id)) == event
            and event.step_id not in input_order[event.trace_id]
        ):
            input_order[event.trace_id].append(event.step_id)
    for event in unique.values():
        grouped[event.trace_id].append(event)
    all_step_traces_mutable: dict[str, set[str]] = defaultdict(set)
    for event in unique.values():
        all_step_traces_mutable[event.step_id].add(event.trace_id)
    all_step_traces = {
        step_id: frozenset(trace_ids) for step_id, trace_ids in all_step_traces_mutable.items()
    }

    traces: list[Trace] = []
    for trace_id in sorted(grouped):
        trace_events = sorted(grouped[trace_id], key=lambda event: event.sort_key)
        sorted_ids = [event.step_id for event in trace_events]
        if input_order[trace_id] != sorted_ids:
            warnings.append(
                _warning(
                    "out_of_order_input",
                    f"trace[{trace_id}]",
                    "input events were reordered chronologically",
                    "export chronological rows or rely on the documented deterministic ordering",
                )
            )
        timestamp_groups: dict[int, int] = defaultdict(int)
        for event in trace_events:
            timestamp_groups[event.sort_key[0]] += 1
        if any(count > 1 for count in timestamp_groups.values()):
            warnings.append(
                _warning(
                    "equal_timestamps",
                    f"trace[{trace_id}]",
                    "equal timestamps were ordered by step_id",
                    "provide distinct timestamps when source order has semantic meaning",
                )
            )
        relationship_errors, relationship_warnings = _trace_relationship_issues(
            trace_id, trace_events, all_step_traces
        )
        errors.extend(relationship_errors)
        warnings.extend(relationship_warnings)
        trace, outcome_warning = _make_trace(trace_id, trace_events)
        traces.append(trace)
        if outcome_warning is not None:
            warnings.append(outcome_warning)
    if errors:
        raise ValidationError(sorted(errors, key=_issue_sort_key))

    categories = {event.category for event in unique.values()}
    if len(categories) > high_cardinality_threshold:
        warnings.append(
            _warning(
                "high_cardinality_categories",
                "dataset",
                "operation/component labels exceed the configured cardinality threshold",
                "normalize dynamic identifiers out of component labels before analysis",
            )
        )

    normalized_events = tuple(event for trace in traces for event in trace.events)
    return NormalizedDataset(
        events=normalized_events,
        traces=tuple(traces),
        warnings=tuple(sorted(set(warnings), key=_issue_sort_key)),
        input_format=input_format,
        input_record_count=len(source_records),
    )


def _issue_sort_key(issue: Issue) -> tuple[str, str, str, str, str]:
    return (issue.severity, issue.code, issue.location, issue.message, issue.hint)


def serialize_normalized_jsonl(dataset: NormalizedDataset) -> str:
    """Serialize accepted events as deterministic UTF-8 JSON Lines text."""

    serialized = (
        json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for event in dataset.events
    )
    return "".join(f"{line}\n" for line in serialized)
