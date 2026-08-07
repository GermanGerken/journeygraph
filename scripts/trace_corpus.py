"""Prepare and verify publishable OTLP/JSON test fixtures.

Collector file-exporter input is JSONL (one request per line). JourneyGraph's experimental
importer accepts one ExportTraceServiceRequest JSON object, so conversion stays in this
repository-only harness rather than silently widening product compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re

# Git is invoked below with a fixed argument vector and no shell.
import subprocess  # nosec B404
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]

VERSION = "1.0"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PROVENANCE_SCHEMA_PATH = REPOSITORY_ROOT / "test-data" / "schemas" / "provenance-v1.schema.json"
PIN_SCHEMA_PATH = REPOSITORY_ROOT / "test-data" / "schemas" / "pins-v1.schema.json"
PIN_MANIFEST_PATH = REPOSITORY_ROOT / "test-data" / "pins.json"
FIXTURE_ROOTS = (
    REPOSITORY_ROOT / "tests_integration" / "fixtures" / "otlp",
    REPOSITORY_ROOT / "test-data" / "fixtures" / "integration",
)
EXPLICIT_FIXTURES = (REPOSITORY_ROOT / "tests_functional" / "fixtures" / "otlp_trace.json",)
PRIVATE_PREFIXES = ("data/private/", "data/external-corpus/", "test-data/raw/", "test-data/work/")

TRACE_ID = re.compile(r"^[0-9A-Fa-f]{32}$")
SPAN_ID = re.compile(r"^[0-9A-Fa-f]{16}$")
ENV_VALUE = re.compile(r"^[A-Za-z0-9._:/@+-]+$")
EMAIL = re.compile(r"(?i)(?<![\w.-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?![\w.-])")
PHONE = re.compile(r"(?<!\w)(?:\+\d{1,3}[ .()-]*)?(?:\d[ .()-]*){9,15}(?!\w)")
ABSOLUTE_PATH = re.compile(r"(?i)(?:/(?:Users|home|private|var/folders)/|[a-z]:\\Users\\)")
SECRET_VALUE = re.compile(
    r"(?i)(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"\bAKIA[0-9A-Z]{16}\b|\bgh[oprsu]_[A-Za-z0-9]{20,}\b|\bsk-[A-Za-z0-9_-]{16,}\b|"
    r"(?:api[_ .-]?key|authorization|password|secret)\s*[:=]\s*\S+)"
)

ANY_VALUE_KEYS = (
    "stringValue",
    "boolValue",
    "intValue",
    "doubleValue",
    "arrayValue",
    "kvlistValue",
    "bytesValue",
)
SAFE_RESOURCE_ATTRIBUTES = frozenset(
    {
        "service.name",
        "service.version",
        "deployment.environment.name",
        "telemetry.sdk.name",
        "telemetry.sdk.language",
        "telemetry.sdk.version",
    }
)
SAFE_SPAN_ATTRIBUTES = frozenset(
    {
        "openinference.span.kind",
        "tool.name",
        "agent.name",
        "llm.model_name",
        "gen_ai.request.model",
        "llm.token_count.prompt",
        "llm.token_count.completion",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "llm.cost.total",
        "llm.cost.prompt",
        "llm.cost.completion",
        "journeygraph.outcome",
        "journeygraph.scenario",
        "test.unknown.scalar",
        "test.any.string",
        "test.any.bool",
        "test.any.int",
        "test.any.double",
        "test.any.array",
        "test.any.kvlist",
        "test.any.bytes",
    }
)
SAFE_SENSITIVE_COUNTER_KEYS = frozenset(
    {
        "llm.token_count.prompt",
        "llm.token_count.completion",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
    }
)
SENSITIVE_KEY_PARTS = (
    "account",
    "address",
    "api_key",
    "apikey",
    "authorization",
    "baggage",
    "bearer",
    "body",
    "choice",
    "cookie",
    "credential",
    "document",
    "email",
    "first_name",
    "full_name",
    "header",
    "input_value",
    "last_name",
    "message",
    "output_value",
    "password",
    "personal",
    "phone",
    "prompt",
    "response",
    "secret",
    "session",
    "token",
    "tool_argument",
    "tool_parameters",
    "tool_result",
    "url",
    "user",
    "visitor",
)


class CorpusError(ValueError):
    """A safe, non-value-echoing corpus validation failure."""


def _load_json_object(path: Path, location: str) -> dict[str, object]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CorpusError(f"{location}: cannot read valid UTF-8 JSON") from error
    return dict(_object(value, location))


def _validate_schema(value: Mapping[str, object], schema_path: Path, location: str) -> None:
    schema = _load_json_object(schema_path, f"{location} schema")
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as schema_error:
        raise CorpusError(f"{location}: repository schema is invalid") from schema_error
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(
        validator.iter_errors(dict(value)),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        validation_error = errors[0]
        field = "/".join(str(part) for part in validation_error.absolute_path) or "<root>"
        raise CorpusError(
            f"{location}: schema violation at {field} ({validation_error.validator or 'unknown'})"
        )


def _load_pins() -> dict[str, object]:
    pins = _load_json_object(PIN_MANIFEST_PATH, "pin manifest")
    _validate_schema(pins, PIN_SCHEMA_PATH, "pin manifest")
    return pins


@dataclass(frozen=True)
class SpanRef:
    span: Mapping[str, object]
    resource_attributes: Mapping[str, object]
    ordinal: int

    @property
    def trace_id(self) -> str:
        return cast(str, self.span["traceId"]).casefold()

    @property
    def span_id(self) -> str:
        return cast(str, self.span["spanId"]).casefold()

    @property
    def parent_id(self) -> str | None:
        value = self.span.get("parentSpanId")
        return value.casefold() if isinstance(value, str) and value else None

    @property
    def start_ns(self) -> int:
        return _int(self.span.get("startTimeUnixNano"), "span.startTimeUnixNano")

    @property
    def end_ns(self) -> int:
        return _int(self.span.get("endTimeUnixNano"), "span.endTimeUnixNano")

    @property
    def service(self) -> str:
        value = self.resource_attributes.get("service.name")
        return value if isinstance(value, str) else "unknown-service"


def _object(value: object, location: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise CorpusError(f"{location}: expected object")
    return cast(Mapping[str, object], value)


def _list(value: object, location: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise CorpusError(f"{location}: expected array")
    return value


def _int(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise CorpusError(f"{location}: expected protobuf JSON integer")
    try:
        return int(value)
    except ValueError as error:
        raise CorpusError(f"{location}: malformed protobuf JSON integer") from error


def _decode_any_value(value: object, location: str) -> object:
    wrapped = _object(value, location)
    present = [key for key in ANY_VALUE_KEYS if key in wrapped]
    if len(present) != 1:
        raise CorpusError(f"{location}: AnyValue must have exactly one recognized variant")
    key = present[0]
    decoded = wrapped[key]
    if key == "stringValue" and not isinstance(decoded, str):
        raise CorpusError(f"{location}: stringValue must be a string")
    if key == "boolValue" and not isinstance(decoded, bool):
        raise CorpusError(f"{location}: boolValue must be boolean")
    if key == "intValue":
        _int(decoded, location)
    if key == "doubleValue" and (
        isinstance(decoded, bool) or not isinstance(decoded, (int, float))
    ):
        raise CorpusError(f"{location}: doubleValue must be numeric")
    if key == "arrayValue":
        array = _object(decoded, location)
        for index, item in enumerate(_list(array.get("values", []), f"{location}.values")):
            _decode_any_value(item, f"{location}.values[{index}]")
    if key == "kvlistValue":
        kvlist = _object(decoded, location)
        _attribute_map(kvlist.get("values", []), f"{location}.values")
    if key == "bytesValue" and not isinstance(decoded, str):
        raise CorpusError(f"{location}: bytesValue must be base64 text")
    return decoded


def _attribute_map(value: object, location: str) -> dict[str, object]:
    attributes: dict[str, object] = {}
    for index, raw in enumerate(_list(value, location)):
        attribute = _object(raw, f"{location}[{index}]")
        key = attribute.get("key")
        if not isinstance(key, str) or not key:
            raise CorpusError(f"{location}[{index}].key: expected non-empty string")
        if key in attributes:
            raise CorpusError(f"{location}[{index}]: duplicate attribute key")
        attributes[key] = _decode_any_value(attribute.get("value"), f"{location}[{index}].value")
    return attributes


def _requests(path: Path) -> list[dict[str, object]]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise CorpusError(f"cannot read UTF-8 input: {path.name}") from error
    if not text.strip():
        raise CorpusError("input is empty")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        requests: list[dict[str, object]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise CorpusError(f"line {line_number}: invalid Collector JSONL") from error
            requests.append(dict(_object(value, f"line {line_number}")))
        return requests
    return [dict(_object(value, "root"))]


def _span_refs(requests: Sequence[Mapping[str, object]]) -> list[SpanRef]:
    refs: list[SpanRef] = []
    for request_index, request in enumerate(requests):
        resource_spans = _list(
            request.get("resourceSpans"), f"request[{request_index}].resourceSpans"
        )
        for _resource_index, raw_resource_span in enumerate(resource_spans):
            resource_span = _object(raw_resource_span, "resourceSpans[]")
            resource = _object(resource_span.get("resource", {}), "resource")
            resource_attributes = _attribute_map(
                resource.get("attributes", []), "resource.attributes"
            )
            for raw_scope_span in _list(resource_span.get("scopeSpans"), "scopeSpans"):
                scope_span = _object(raw_scope_span, "scopeSpans[]")
                for raw_span in _list(scope_span.get("spans"), "spans"):
                    span = _object(raw_span, "spans[]")
                    trace_id = span.get("traceId")
                    span_id = span.get("spanId")
                    if (
                        not isinstance(trace_id, str)
                        or TRACE_ID.fullmatch(trace_id) is None
                        or set(trace_id) == {"0"}
                    ):
                        raise CorpusError("span.traceId: expected non-zero 32-character hex")
                    if (
                        not isinstance(span_id, str)
                        or SPAN_ID.fullmatch(span_id) is None
                        or set(span_id) == {"0"}
                    ):
                        raise CorpusError("span.spanId: expected non-zero 16-character hex")
                    parent_id = span.get("parentSpanId")
                    if parent_id not in (None, "") and (
                        not isinstance(parent_id, str)
                        or SPAN_ID.fullmatch(parent_id) is None
                        or set(parent_id) == {"0"}
                    ):
                        raise CorpusError("span.parentSpanId: expected non-zero 16-character hex")
                    name = span.get("name")
                    if not isinstance(name, str) or not name.strip():
                        raise CorpusError("span.name: expected non-empty string")
                    start = _int(span.get("startTimeUnixNano"), "span.startTimeUnixNano")
                    end = _int(span.get("endTimeUnixNano"), "span.endTimeUnixNano")
                    if start < 0 or end < start:
                        raise CorpusError("span timestamps: expected non-negative ordered values")
                    _attribute_map(span.get("attributes", []), "span.attributes")
                    refs.append(SpanRef(span, resource_attributes, len(refs)))
    return refs


def _status_code(span: Mapping[str, object]) -> int:
    status = _object(span.get("status", {}), "span.status")
    code = status.get("code", 0)
    if isinstance(code, str) and code.startswith("STATUS_CODE_"):
        names = {"STATUS_CODE_UNSET": 0, "STATUS_CODE_OK": 1, "STATUS_CODE_ERROR": 2}
        if code not in names:
            raise CorpusError("span.status.code: unknown enum name")
        return names[code]
    parsed = _int(code, "span.status.code")
    if parsed not in {0, 1, 2}:
        raise CorpusError("span.status.code: expected 0, 1, or 2")
    return parsed


def _features(refs: Sequence[SpanRef]) -> set[str]:
    if not refs:
        return set()
    span_ids = {ref.span_id for ref in refs}
    features: set[str] = set()
    if len({ref.service for ref in refs}) > 1:
        features.add("multi_service")
    if any(ref.parent_id in span_ids for ref in refs):
        features.add("parent_child")
    if any(_status_code(ref.span) == 2 for ref in refs):
        features.add("error")
    starts = [ref.start_ns for ref in sorted(refs, key=lambda item: item.ordinal)]
    if starts != sorted(starts):
        features.add("out_of_order")
    siblings: dict[str, list[SpanRef]] = defaultdict(list)
    for ref in refs:
        if ref.parent_id is not None:
            siblings[ref.parent_id].append(ref)
    for group in siblings.values():
        ordered = sorted(group, key=lambda item: (item.start_ns, item.span_id))
        if any(left.end_ns > right.start_ns for left, right in pairwise(ordered)):
            features.add("concurrent_siblings")
            break
    return features


def _select_trace_ids(refs: Sequence[SpanRef], max_traces: int) -> set[str]:
    by_trace: dict[str, list[SpanRef]] = defaultdict(list)
    for ref in refs:
        by_trace[ref.trace_id].append(ref)
    if max_traces <= 0 or len(by_trace) <= max_traces:
        return set(by_trace)
    desired = {"multi_service", "parent_child", "concurrent_siblings", "error", "out_of_order"}
    selected: list[str] = []
    uncovered = set(desired)
    remaining = set(by_trace)
    while remaining and len(selected) < max_traces:
        best = min(
            remaining,
            key=lambda trace_id: (
                -len(_features(by_trace[trace_id]) & uncovered),
                len(by_trace[trace_id]),
                trace_id,
            ),
        )
        selected.append(best)
        uncovered -= _features(by_trace[best])
        remaining.remove(best)
    return set(selected)


def _normalized_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


def _sensitive_key(key: str) -> bool:
    if key in SAFE_SENSITIVE_COUNTER_KEYS:
        return False
    normalized = _normalized_key(key)
    return any(fragment in normalized for fragment in SENSITIVE_KEY_PARTS)


def _safe_string(value: str, location: str) -> None:
    if EMAIL.search(value):
        raise CorpusError(f"{location}: possible email address")
    if PHONE.search(value) and not TRACE_ID.fullmatch(value) and not SPAN_ID.fullmatch(value):
        raise CorpusError(f"{location}: possible phone number")
    if ABSOLUTE_PATH.search(value):
        raise CorpusError(f"{location}: local absolute path")
    if SECRET_VALUE.search(value):
        raise CorpusError(f"{location}: possible credential or token")


def _scan_content(value: object, location: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            public_provenance_link = location.startswith("provenance") and key in {
                "repository",
                "url",
            }
            if _sensitive_key(str(key)) and not public_provenance_link:
                raise CorpusError(f"{location}: sensitive key")
            _scan_content(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_content(child, f"{location}[{index}]")
    elif isinstance(value, str):
        _safe_string(value, location)


def _safe_label(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorpusError(f"{location}: expected non-empty label")
    if len(value) > 256:
        raise CorpusError(f"{location}: label exceeds 256 characters")
    _safe_string(value, location)
    return value.strip()


def _sanitize_attributes(
    raw: object,
    allowed: frozenset[str],
    location: str,
) -> list[dict[str, object]]:
    sanitized: list[dict[str, object]] = []
    for index, raw_attribute in enumerate(_list(raw, location)):
        attribute = _object(raw_attribute, f"{location}[{index}]")
        key = attribute.get("key")
        if not isinstance(key, str) or not key:
            raise CorpusError(f"{location}[{index}].key: expected non-empty string")
        _decode_any_value(attribute.get("value"), f"{location}[{index}].value")
        if key not in allowed or _sensitive_key(key):
            continue
        value = cast(dict[str, object], attribute["value"])
        _scan_content(value, f"{location}[{index}].value")
        sanitized.append({"key": key, "value": value})
    return sanitized


def _enum_number(value: object, names: Mapping[str, int], location: str) -> int:
    if isinstance(value, str) and value in names:
        return names[value]
    return _int(value, location)


def _sanitize_span(span: Mapping[str, object], offset_ns: int) -> dict[str, object]:
    start = _int(span.get("startTimeUnixNano"), "span.startTimeUnixNano") + offset_ns
    end = _int(span.get("endTimeUnixNano"), "span.endTimeUnixNano") + offset_ns
    kind = _enum_number(
        span.get("kind", 0),
        {
            "SPAN_KIND_UNSPECIFIED": 0,
            "SPAN_KIND_INTERNAL": 1,
            "SPAN_KIND_SERVER": 2,
            "SPAN_KIND_CLIENT": 3,
            "SPAN_KIND_PRODUCER": 4,
            "SPAN_KIND_CONSUMER": 5,
        },
        "span.kind",
    )
    if kind not in range(6):
        raise CorpusError("span.kind: expected enum 0 through 5")
    output: dict[str, object] = {
        "traceId": cast(str, span["traceId"]).casefold(),
        "spanId": cast(str, span["spanId"]).casefold(),
        "name": _safe_label(span.get("name"), "span.name"),
        "kind": kind,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "attributes": _sanitize_attributes(
            span.get("attributes", []), SAFE_SPAN_ATTRIBUTES, "span.attributes"
        ),
        "status": {"code": _status_code(span)},
    }
    parent = span.get("parentSpanId")
    if isinstance(parent, str) and parent:
        output["parentSpanId"] = parent.casefold()
    return output


def _sanitize_requests(
    requests: Sequence[Mapping[str, object]], selected_trace_ids: set[str]
) -> dict[str, object]:
    refs = _span_refs(requests)
    selected_refs = [ref for ref in refs if ref.trace_id in selected_trace_ids]
    if not selected_refs:
        raise CorpusError("selection contains no spans")
    target_start = 1_767_225_600_000_000_000
    offset_ns = target_start - min(ref.start_ns for ref in selected_refs)
    output_resources: list[dict[str, object]] = []
    for request in requests:
        for raw_resource_span in _list(request.get("resourceSpans"), "resourceSpans"):
            resource_span = _object(raw_resource_span, "resourceSpans[]")
            resource = _object(resource_span.get("resource", {}), "resource")
            output_scopes: list[dict[str, object]] = []
            for raw_scope_span in _list(resource_span.get("scopeSpans"), "scopeSpans"):
                scope_span = _object(raw_scope_span, "scopeSpans[]")
                output_spans: list[dict[str, object]] = []
                for raw_span in _list(scope_span.get("spans"), "spans"):
                    span = _object(raw_span, "spans[]")
                    trace_id = span.get("traceId")
                    if isinstance(trace_id, str) and trace_id.casefold() in selected_trace_ids:
                        output_spans.append(_sanitize_span(span, offset_ns))
                if not output_spans:
                    continue
                scope = _object(scope_span.get("scope", {}), "scope")
                output_scope: dict[str, object] = {}
                if "name" in scope:
                    output_scope["name"] = _safe_label(scope["name"], "scope.name")
                if "version" in scope:
                    output_scope["version"] = _safe_label(scope["version"], "scope.version")
                output_scopes.append({"scope": output_scope, "spans": output_spans})
            if output_scopes:
                output_resources.append(
                    {
                        "resource": {
                            "attributes": _sanitize_attributes(
                                resource.get("attributes", []),
                                SAFE_RESOURCE_ATTRIBUTES,
                                "resource.attributes",
                            )
                        },
                        "scopeSpans": output_scopes,
                    }
                )
    output: dict[str, object] = {"resourceSpans": output_resources}
    _scan_content(output)
    return output


def _observed(payload: Mapping[str, object]) -> dict[str, object]:
    refs = _span_refs([payload])
    by_trace: dict[str, list[SpanRef]] = defaultdict(list)
    for ref in refs:
        by_trace[ref.trace_id].append(ref)
    ids_by_trace = {
        trace_id: {ref.span_id for ref in group} for trace_id, group in by_trace.items()
    }
    errors = sum(_status_code(ref.span) == 2 for ref in refs)
    parents = sum(ref.parent_id is not None for ref in refs)
    missing = sum(
        ref.parent_id is not None and ref.parent_id not in ids_by_trace[ref.trace_id]
        for ref in refs
    )
    explicit = 0
    for ref in refs:
        attributes = _attribute_map(ref.span.get("attributes", []), "span.attributes")
        if "journeygraph.outcome" in attributes:
            explicit += 1
    feature_counts = Counter(feature for group in by_trace.values() for feature in _features(group))
    resource_spans = _list(payload.get("resourceSpans"), "resourceSpans")
    scope_count = sum(
        len(_list(_object(item, "resourceSpans[]").get("scopeSpans"), "scopeSpans"))
        for item in resource_spans
    )
    return {
        "resource_spans": len(resource_spans),
        "scope_spans": scope_count,
        "spans": len(refs),
        "traces": len(by_trace),
        "services": len({ref.service for ref in refs}),
        "parent_links": parents,
        "missing_parent_links": missing,
        "error_spans": errors,
        "explicit_outcome_spans": explicit,
        "traces_with_multi_service": feature_counts["multi_service"],
        "traces_with_concurrent_siblings": feature_counts["concurrent_siblings"],
        "traces_out_of_source_order": feature_counts["out_of_order"],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sidecar(path: Path) -> Path:
    return path.with_suffix(".provenance.json")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError as error:
        raise CorpusError("fixture output must be inside the repository") from error


def _requirements_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise CorpusError(f"{path.name}: cannot read requirements lock") from error
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^;\s]+)", line)
        if match is None:
            raise CorpusError(f"{path.name}: invalid lock entry on line {line_number}")
        name, version = match.groups()
        normalized = name.casefold().replace("_", "-")
        if normalized in pins:
            raise CorpusError(f"{path.name}: duplicate requirement on line {line_number}")
        pins[normalized] = version
    if not pins:
        raise CorpusError(f"{path.name}: requirements lock is empty")
    return pins


def _instrumented_source_expectations(pins: Mapping[str, object]) -> dict[str, dict[str, str]]:
    demo = _object(pins.get("otel_demo"), "pin manifest.otel_demo")
    openinference = _object(pins.get("openinference"), "pin manifest.openinference")
    packages = _object(openinference.get("packages"), "pin manifest.openinference.packages")
    instrumentation = cast(str, packages["openinference-instrumentation"])
    otel_python = cast(str, packages["opentelemetry-sdk"])
    return {
        cast(str, demo["repository"]): {
            "version": cast(str, demo["version"]),
            "commit": cast(str, demo["commit"]),
        },
        cast(str, openinference["repository"]): {
            "version": (
                f"openinference-instrumentation {instrumentation}; "
                f"OpenTelemetry Python {otel_python}"
            ),
            "commit": cast(str, openinference["commit"]),
        },
    }


def _validate_instrumented_source(
    provenance: Mapping[str, object], fixture_name: str, pins: Mapping[str, object]
) -> None:
    if provenance.get("classification") != "instrumented-demo":
        return
    source = _object(provenance.get("source"), "provenance.source")
    repository = source.get("repository")
    expectations = _instrumented_source_expectations(pins)
    if not isinstance(repository, str) or repository not in expectations:
        raise CorpusError(f"{fixture_name}: instrumented source is not present in pin manifest")
    expected = expectations[repository]
    if source.get("version") != expected["version"] or source.get("commit") != expected["commit"]:
        raise CorpusError(f"{fixture_name}: instrumented source differs from pin manifest")
    license_record = _object(provenance.get("source_license"), "provenance.source_license")
    license_url = license_record.get("url")
    pinned_license_prefixes = (
        f"{repository.rstrip('/')}/blob/{expected['commit']}/",
        f"{repository.rstrip('/')}/raw/{expected['commit']}/",
    )
    if not isinstance(license_url, str) or not license_url.startswith(pinned_license_prefixes):
        raise CorpusError(f"{fixture_name}: source license URL is not pinned to its source commit")


def _pin_environment(pins: Mapping[str, object]) -> dict[str, str]:
    collector = _object(pins.get("collector"), "pin manifest.collector")
    demo = _object(pins.get("otel_demo"), "pin manifest.otel_demo")
    images = _object(demo.get("images"), "pin manifest.otel_demo.images")
    environment = {
        "DEMO_VERSION": cast(str, demo["version"]),
        "OTEL_DEMO_COMMIT": cast(str, demo["commit"]),
        "JOURNEYGRAPH_COLLECTOR_IMAGE": cast(str, collector["image"]),
    }
    for service, image in sorted(images.items()):
        variable = f"JOURNEYGRAPH_IMAGE_{re.sub(r'[^A-Za-z0-9]+', '_', service).upper()}"
        if not isinstance(image, str) or ENV_VALUE.fullmatch(image) is None:
            raise CorpusError("pin manifest contains an unsafe environment value")
        environment[variable] = image
    if any(ENV_VALUE.fullmatch(value) is None for value in environment.values()):
        raise CorpusError("pin manifest contains an unsafe environment value")
    return environment


def _check_pin_consistency() -> None:
    pins = _load_pins()
    collector = _object(pins.get("collector"), "pin manifest.collector")
    demo = _object(pins.get("otel_demo"), "pin manifest.otel_demo")
    images = _object(demo.get("images"), "pin manifest.otel_demo.images")
    if images.get("otel-collector") != collector.get("image"):
        raise CorpusError("pin manifest collector image differs from Demo dependency closure")

    openinference = _object(pins.get("openinference"), "pin manifest.openinference")
    expected_packages = _object(
        openinference.get("packages"), "pin manifest.openinference.packages"
    )
    locked_packages = _requirements_pins(
        REPOSITORY_ROOT / "test-data" / "openinference" / "requirements.lock"
    )
    for package, version in expected_packages.items():
        if locked_packages.get(package) != version:
            raise CorpusError("OpenInference requirements lock differs from pin manifest")

    collector_compose = (REPOSITORY_ROOT / "test-data" / "collector" / "compose.yaml").read_text(
        encoding="utf-8"
    )
    if "image: ${JOURNEYGRAPH_COLLECTOR_IMAGE:?}" not in collector_compose:
        raise CorpusError("Collector Compose file does not consume the pin manifest")
    demo_override = (REPOSITORY_ROOT / "test-data" / "collector" / "demo-override.yaml").read_text(
        encoding="utf-8"
    )
    for variable in _pin_environment(pins):
        if variable.startswith("JOURNEYGRAPH_IMAGE_") and f"${{{variable}:?}}" not in demo_override:
            raise CorpusError("Demo Compose override does not consume every pinned image")

    for relative in (
        "test-data/openinference/capture.sh",
        "test-data/opentelemetry-demo/capture.sh",
    ):
        capture = (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        if "write-pin-env" not in capture:
            raise CorpusError(f"{Path(relative).name}: capture does not consume pin manifest")
    demo_capture = (REPOSITORY_ROOT / "test-data" / "opentelemetry-demo" / "capture.sh").read_text(
        encoding="utf-8"
    )
    for upstream_environment in ("$work_root/.env", "$work_root/.env.override"):
        if f'--env-file "{upstream_environment}"' not in demo_capture:
            raise CorpusError("Demo capture does not load the pinned upstream environment")
    if (REPOSITORY_ROOT / "test-data" / "pins.env").exists():
        raise CorpusError("legacy duplicate pin file must not exist")

    for relative in (
        "test-data/openinference/provenance-template.json",
        "test-data/opentelemetry-demo/provenance-template.json",
    ):
        template = _load_json_object(REPOSITORY_ROOT / relative, Path(relative).name)
        _validate_instrumented_source(template, Path(relative).name, pins)


def write_pin_env(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    relative = _relative(output)
    if not relative.startswith("test-data/work/") or output.suffix != ".env":
        raise CorpusError("pin environment output must be an .env file under test-data/work")
    environment = _pin_environment(_load_pins())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(f"{name}={value}\n" for name, value in sorted(environment.items())),
        encoding="utf-8",
    )
    print(relative)
    return 0


def _validate_provenance(
    provenance: Mapping[str, object], fixture: Path, payload: Mapping[str, object]
) -> None:
    _validate_schema(provenance, PROVENANCE_SCHEMA_PATH, fixture.name)
    if provenance["fixture"] != _relative(fixture):
        raise CorpusError(f"{fixture.name}: provenance fixture path mismatch")
    if provenance["content_sha256"] != _sha256(fixture):
        raise CorpusError(f"{fixture.name}: provenance digest mismatch")
    if provenance["observed"] != _observed(payload):
        raise CorpusError(f"{fixture.name}: provenance observed dimensions mismatch")
    _validate_instrumented_source(provenance, fixture.name, _load_pins())
    _scan_content(dict(provenance), "provenance")


def prepare(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    template_path = Path(args.provenance_template).resolve()
    requests = _requests(input_path)
    refs = _span_refs(requests)
    selected = _select_trace_ids(refs, args.max_traces)
    payload = _sanitize_requests(requests, selected)
    _write_json(output_path, payload)
    template = dict(_object(json.loads(template_path.read_text(encoding="utf-8")), "provenance"))
    template["fixture"] = _relative(output_path)
    template["content_sha256"] = _sha256(output_path)
    template["observed"] = _observed(payload)
    _write_json(_sidecar(output_path), template)
    _validate_provenance(template, output_path, payload)
    print(json.dumps(template["observed"], sort_keys=True))
    return 0


def _fixture_paths() -> list[Path]:
    fixtures: set[Path] = set(EXPLICIT_FIXTURES)
    for root in FIXTURE_ROOTS:
        if root.exists():
            fixtures.update(
                path for path in root.rglob("*.json") if not path.name.endswith(".provenance.json")
            )
    return sorted(fixtures)


def _check_private_paths() -> None:
    result = subprocess.run(  # nosec B603 B607
        ["git", "ls-files", "-z"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    for raw_path in result.stdout.decode("utf-8").split("\0"):
        if raw_path and raw_path.startswith(PRIVATE_PREFIXES):
            raise CorpusError("ignored raw/private/external corpus path is tracked by git")


def check(_args: argparse.Namespace) -> int:
    fixtures = _fixture_paths()
    if not fixtures:
        raise CorpusError("no OTLP fixtures found")
    _check_pin_consistency()
    _check_private_paths()
    for fixture in fixtures:
        payload = _object(json.loads(fixture.read_text(encoding="utf-8")), fixture.name)
        _span_refs([payload])
        _scan_content(dict(payload), fixture.name)
        sidecar = _sidecar(fixture)
        if not sidecar.is_file():
            raise CorpusError(f"{fixture.name}: missing provenance sidecar")
        provenance = _object(json.loads(sidecar.read_text(encoding="utf-8")), sidecar.name)
        _validate_provenance(provenance, fixture, payload)
    print(f"validated {len(fixtures)} publishable OTLP fixtures")
    return 0


def inspect_fixture(args: argparse.Namespace) -> int:
    payload = _object(json.loads(Path(args.fixture).read_text(encoding="utf-8")), "root")
    print(json.dumps(_observed(payload), indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare", help="sanitize Collector JSONL")
    prepare_parser.add_argument("--input", required=True)
    prepare_parser.add_argument("--output", required=True)
    prepare_parser.add_argument("--provenance-template", required=True)
    prepare_parser.add_argument("--max-traces", type=int, default=0)
    prepare_parser.set_defaults(handler=prepare)
    check_parser = subparsers.add_parser("check", help="validate committed corpus")
    check_parser.set_defaults(handler=check)
    inspect_parser = subparsers.add_parser("inspect", help="print structural dimensions")
    inspect_parser.add_argument("fixture")
    inspect_parser.set_defaults(handler=inspect_fixture)
    pin_env_parser = subparsers.add_parser(
        "write-pin-env", help="write ignored Compose environment from the authoritative pins"
    )
    pin_env_parser.add_argument("--output", required=True)
    pin_env_parser.set_defaults(handler=write_pin_env)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return cast(int, args.handler(args))
    except (CorpusError, json.JSONDecodeError, OSError, subprocess.CalledProcessError) as error:
        print(f"trace corpus check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
