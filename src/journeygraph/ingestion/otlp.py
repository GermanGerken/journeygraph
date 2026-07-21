"""Narrow OTLP/HTTP JSON trace-request importer."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from journeygraph.domain.models import SourceRecord
from journeygraph.exceptions import FormatError

_TRACE_ID = re.compile(r"^[0-9A-Fa-f]{32}$")
_SPAN_ID = re.compile(r"^[0-9A-Fa-f]{16}$")
_KIND_NAMES = {
    0: "unspecified",
    1: "internal",
    2: "server",
    3: "client",
    4: "producer",
    5: "consumer",
}
_STATUS_NAMES = {0: "unset", 1: "ok", 2: "error"}
_OPENINFERENCE_KINDS = frozenset(
    {
        "LLM",
        "EMBEDDING",
        "CHAIN",
        "RETRIEVER",
        "RERANKER",
        "TOOL",
        "AGENT",
        "GUARDRAIL",
        "EVALUATOR",
        "PROMPT",
    }
)


def _format_error(code: str, location: str, message: str, hint: str) -> FormatError:
    return FormatError(f"[{code}] {location}: {message}. Fix: {hint}")


def _as_object(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _format_error(
            "invalid_otlp_shape",
            location,
            "expected a JSON object",
            "use an OTLP ExportTraceServiceRequest JSON body",
        )
    return cast(Mapping[str, object], value)


def _as_list(value: object, location: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise _format_error(
            "invalid_otlp_shape",
            location,
            "expected a JSON array",
            "use the official OTLP lowerCamelCase JSON shape",
        )
    return value


def _decode_any_value(value: object, location: str) -> object:
    wrapped = _as_object(value, location)
    present = [
        key
        for key in (
            "stringValue",
            "boolValue",
            "intValue",
            "doubleValue",
            "arrayValue",
            "kvlistValue",
            "bytesValue",
        )
        if key in wrapped
    ]
    if len(present) != 1:
        raise _format_error(
            "invalid_otlp_attribute",
            location,
            "AnyValue must contain exactly one recognized value field",
            "encode one official protobuf AnyValue variant",
        )
    key = present[0]
    decoded = wrapped[key]
    if key == "intValue":
        if isinstance(decoded, bool) or not isinstance(decoded, (str, int)):
            raise _format_error(
                "invalid_otlp_attribute",
                location,
                "intValue is not a decimal string or integer",
                "encode a signed decimal integer",
            )
        try:
            return int(decoded)
        except ValueError as error:
            raise _format_error(
                "invalid_otlp_attribute",
                location,
                "intValue is malformed",
                "encode a signed decimal integer",
            ) from error
    if key == "doubleValue":
        if isinstance(decoded, bool) or not isinstance(decoded, (int, float)):
            raise _format_error(
                "invalid_otlp_attribute",
                location,
                "doubleValue is not numeric",
                "encode a finite JSON number",
            )
        return decoded
    if key == "stringValue" and not isinstance(decoded, str):
        raise _format_error(
            "invalid_otlp_attribute",
            location,
            "stringValue is not a string",
            "encode a JSON string",
        )
    if key == "boolValue" and not isinstance(decoded, bool):
        raise _format_error(
            "invalid_otlp_attribute", location, "boolValue is not a boolean", "encode true or false"
        )
    if key in {"arrayValue", "kvlistValue", "bytesValue"}:
        return None
    return decoded


def _attributes(value: object, location: str) -> dict[str, object]:
    if value is None:
        return {}
    decoded: dict[str, object] = {}
    for index, raw_attribute in enumerate(_as_list(value, location)):
        attribute_location = f"{location}[{index}]"
        attribute = _as_object(raw_attribute, attribute_location)
        key = attribute.get("key")
        if not isinstance(key, str) or not key:
            raise _format_error(
                "invalid_otlp_attribute",
                f"{attribute_location}.key",
                "attribute key is missing or invalid",
                "provide a non-empty string key",
            )
        if key in decoded:
            raise _format_error(
                "duplicate_otlp_attribute",
                attribute_location,
                "attribute keys must be unique within one entity",
                "remove the duplicate attribute key",
            )
        decoded[key] = _decode_any_value(attribute.get("value"), f"{attribute_location}.value")
    return decoded


def _identifier(value: object, *, location: str, trace: bool, optional: bool = False) -> str | None:
    if optional and value in (None, ""):
        return None
    pattern = _TRACE_ID if trace else _SPAN_ID
    expected = "32" if trace else "16"
    if not isinstance(value, str) or pattern.fullmatch(value) is None or set(value) == {"0"}:
        kind = "traceId" if trace else "spanId"
        raise _format_error(
            "invalid_otlp_id",
            location,
            f"{kind} must be non-zero {expected}-character hexadecimal",
            "use the official OTLP identifier encoding",
        )
    return value.casefold()


def _integer(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _format_error(
            "invalid_otlp_integer",
            location,
            "expected a decimal integer string or JSON integer",
            "use the official OTLP JSON integer encoding",
        )
    try:
        return int(value)
    except ValueError as error:
        raise _format_error(
            "invalid_otlp_integer", location, "integer value is malformed", "use base-10 digits"
        ) from error


def _timestamp(nanoseconds: int, location: str) -> str:
    if nanoseconds < 0:
        raise _format_error(
            "invalid_otlp_timestamp",
            location,
            "timestamp cannot be negative",
            "use Unix epoch nanoseconds",
        )
    seconds, nanos = divmod(nanoseconds, 1_000_000_000)
    try:
        base = datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise _format_error(
            "invalid_otlp_timestamp",
            location,
            "timestamp is outside the supported datetime range",
            "use a valid Unix epoch timestamp",
        ) from error
    return f"{base:%Y-%m-%dT%H:%M:%S}.{nanos:09d}Z"


def _number(attributes: Mapping[str, object], key: str) -> int | Decimal | None:
    value = attributes.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    if parsed == parsed.to_integral_value():
        return int(parsed)
    return parsed


def _first_string(attributes: Mapping[str, object], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = attributes.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _record_from_span(
    span: Mapping[str, object],
    resource_attributes: Mapping[str, object],
    location: str,
    sequence: int,
) -> SourceRecord:
    trace_id = _identifier(span.get("traceId"), location=f"{location}.traceId", trace=True)
    span_id = _identifier(span.get("spanId"), location=f"{location}.spanId", trace=False)
    parent_id = _identifier(
        span.get("parentSpanId"), location=f"{location}.parentSpanId", trace=False, optional=True
    )
    name = span.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _format_error(
            "invalid_otlp_span",
            f"{location}.name",
            "span name is missing",
            "provide a non-empty operational span name",
        )
    kind = span.get("kind", 0)
    if isinstance(kind, bool) or not isinstance(kind, int) or kind not in _KIND_NAMES:
        raise _format_error(
            "invalid_otlp_span_kind",
            f"{location}.kind",
            "span kind must be an integer from 0 through 5",
            "use the official SpanKind numeric enum",
        )
    start_ns = _integer(span.get("startTimeUnixNano"), f"{location}.startTimeUnixNano")
    end_ns = _integer(span.get("endTimeUnixNano"), f"{location}.endTimeUnixNano")
    if end_ns < start_ns:
        raise _format_error(
            "invalid_otlp_duration",
            location,
            "endTimeUnixNano precedes startTimeUnixNano",
            "correct the span timestamps so end is not earlier than start",
        )

    span_attributes = _attributes(span.get("attributes", []), f"{location}.attributes")
    oi_kind = span_attributes.get("openinference.span.kind")
    operation_type = _KIND_NAMES[kind]
    if isinstance(oi_kind, str) and oi_kind.upper() in _OPENINFERENCE_KINDS:
        operation_type = oi_kind.casefold()
    component = (
        _first_string(span_attributes, ("tool.name", "agent.name", "llm.model_name")) or name
    )

    status_object = _as_object(span.get("status", {}), f"{location}.status")
    status_code = status_object.get("code", 0)
    if (
        isinstance(status_code, bool)
        or not isinstance(status_code, int)
        or status_code not in _STATUS_NAMES
    ):
        raise _format_error(
            "invalid_otlp_status",
            f"{location}.status.code",
            "status code must be integer 0, 1, or 2",
            "use the official StatusCode numeric enum",
        )

    metadata_sources = (
        ("service", resource_attributes.get("service.name")),
        ("environment", resource_attributes.get("deployment.environment.name")),
        ("model", _first_string(span_attributes, ("gen_ai.request.model", "llm.model_name"))),
        ("agent", span_attributes.get("agent.name")),
        ("cohort", span_attributes.get("journeygraph.cohort")),
    )
    metadata: dict[str, object] = {
        metadata_key: metadata_value
        for metadata_key, metadata_value in metadata_sources
        if isinstance(metadata_value, (str, int, float, bool))
    }

    data: dict[str, object] = {
        "schema_version": "1.0",
        "trace_id": trace_id,
        "step_id": span_id,
        "timestamp": _timestamp(start_ns, f"{location}.startTimeUnixNano"),
        "operation_type": operation_type,
        "component": component,
        "duration_ms": Decimal(end_ns - start_ns) / Decimal(1_000_000),
        "status": _STATUS_NAMES[status_code],
    }
    if parent_id is not None:
        data["parent_step_id"] = parent_id
    explicit_outcome = span_attributes.get("journeygraph.outcome")
    if isinstance(explicit_outcome, str):
        data["outcome"] = explicit_outcome.casefold()
    prompt_tokens = _number(span_attributes, "llm.token_count.prompt")
    completion_tokens = _number(span_attributes, "llm.token_count.completion")
    if prompt_tokens is None:
        prompt_tokens = _number(span_attributes, "gen_ai.usage.input_tokens")
    if completion_tokens is None:
        completion_tokens = _number(span_attributes, "gen_ai.usage.output_tokens")
    if isinstance(prompt_tokens, int):
        data["input_tokens"] = prompt_tokens
    if isinstance(completion_tokens, int):
        data["output_tokens"] = completion_tokens
    total_cost = _number(span_attributes, "llm.cost.total")
    if total_cost is None:
        prompt_cost = _number(span_attributes, "llm.cost.prompt") or 0
        completion_cost = _number(span_attributes, "llm.cost.completion") or 0
        if prompt_cost or completion_cost:
            total_cost = prompt_cost + completion_cost
    if total_cost is not None:
        data["cost_usd"] = total_cost
    if metadata:
        data["metadata"] = metadata
    return SourceRecord(data, location, sequence, timestamp_ns=start_ns)


def read_otlp_json(path: Path) -> tuple[SourceRecord, ...]:
    """Read one uncompressed OTLP ExportTraceServiceRequest JSON body."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise _format_error(
            "malformed_otlp_json",
            f"line {error.lineno}, column {error.colno}",
            "file is not valid JSON",
            "provide one uncompressed OTLP/HTTP JSON trace request body",
        ) from error
    except ValueError as error:
        raise _format_error(
            "invalid_otlp_json_value",
            "root",
            "JSON value exceeds decoder limits",
            "use official bounded OTLP JSON scalar encodings",
        ) from error
    root = _as_object(payload, "root")
    resource_spans = _as_list(root.get("resourceSpans"), "root.resourceSpans")
    records: list[SourceRecord] = []
    for resource_index, raw_resource_span in enumerate(resource_spans):
        resource_location = f"resourceSpans[{resource_index}]"
        resource_span = _as_object(raw_resource_span, resource_location)
        resource = _as_object(resource_span.get("resource", {}), f"{resource_location}.resource")
        resource_attributes = _attributes(
            resource.get("attributes", []), f"{resource_location}.resource.attributes"
        )
        scope_spans = _as_list(resource_span.get("scopeSpans"), f"{resource_location}.scopeSpans")
        for scope_index, raw_scope_span in enumerate(scope_spans):
            scope_location = f"{resource_location}.scopeSpans[{scope_index}]"
            scope_span = _as_object(raw_scope_span, scope_location)
            spans = _as_list(scope_span.get("spans"), f"{scope_location}.spans")
            for span_index, raw_span in enumerate(spans):
                span_location = f"{scope_location}.spans[{span_index}]"
                span = _as_object(raw_span, span_location)
                records.append(
                    _record_from_span(span, resource_attributes, span_location, len(records))
                )
    return tuple(records)
