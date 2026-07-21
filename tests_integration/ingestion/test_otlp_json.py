from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from journeygraph.api import validate_file

_TRACE_ID = "5B8EFFF798038103D269B633813FC60C"
_ROOT_SPAN_ID = "1111111111111111"
_CHILD_SPAN_ID = "2222222222222222"


def _attribute(key: str, variant: str, value: object) -> dict[str, object]:
    return {"key": key, "value": {variant: value}}


def _official_otlp_payload() -> dict[str, object]:
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _attribute("service.name", "stringValue", "journey-api"),
                        _attribute(
                            "deployment.environment.name",
                            "stringValue",
                            "integration",
                        ),
                        _attribute(
                            "authorization",
                            "stringValue",
                            "authorization-leak-sentinel",
                        ),
                    ],
                    "droppedAttributesCount": 0,
                },
                "scopeSpans": [
                    {
                        "scope": {
                            "name": "journeygraph.integration",
                            "version": "1.0.0",
                            "attributes": [],
                            "droppedAttributesCount": 0,
                        },
                        "spans": [
                            {
                                "traceId": _TRACE_ID,
                                "spanId": _ROOT_SPAN_ID,
                                "traceState": "vendor=value",
                                "name": "agent-run",
                                "kind": 1,
                                "startTimeUnixNano": "1767225600000000123",
                                "endTimeUnixNano": "1767225600002000123",
                                "attributes": [
                                    _attribute(
                                        "openinference.span.kind",
                                        "stringValue",
                                        "AGENT",
                                    ),
                                    _attribute("agent.name", "stringValue", "Planner"),
                                    _attribute(
                                        "journeygraph.outcome",
                                        "stringValue",
                                        "success",
                                    ),
                                    _attribute(
                                        "journeygraph.cohort",
                                        "stringValue",
                                        "synthetic",
                                    ),
                                    _attribute(
                                        "input.value",
                                        "stringValue",
                                        "prompt-leak-sentinel",
                                    ),
                                    _attribute(
                                        "output.value",
                                        "stringValue",
                                        "output-leak-sentinel",
                                    ),
                                    _attribute("user.id", "stringValue", "private-user"),
                                    _attribute(
                                        "session.id",
                                        "stringValue",
                                        "private-session",
                                    ),
                                ],
                                "droppedAttributesCount": 0,
                                "events": [],
                                "droppedEventsCount": 0,
                                "links": [],
                                "droppedLinksCount": 0,
                                "status": {
                                    "message": "status-leak-sentinel",
                                    "code": 1,
                                },
                                "flags": 1,
                            },
                            {
                                "traceId": _TRACE_ID,
                                "spanId": _CHILD_SPAN_ID,
                                "parentSpanId": _ROOT_SPAN_ID,
                                "name": "tool-call",
                                "kind": 3,
                                "startTimeUnixNano": "1767225600003000456",
                                "endTimeUnixNano": "1767225600004500456",
                                "attributes": [
                                    _attribute(
                                        "openinference.span.kind",
                                        "stringValue",
                                        "TOOL",
                                    ),
                                    _attribute(
                                        "tool.name",
                                        "stringValue",
                                        "Weather API",
                                    ),
                                    _attribute(
                                        "llm.model_name",
                                        "stringValue",
                                        "demo-model",
                                    ),
                                    _attribute(
                                        "llm.token_count.prompt",
                                        "intValue",
                                        "7",
                                    ),
                                    _attribute(
                                        "llm.token_count.completion",
                                        "intValue",
                                        "3",
                                    ),
                                    _attribute("llm.cost.total", "doubleValue", 0.004),
                                    _attribute(
                                        "tool.parameters",
                                        "stringValue",
                                        "tool-argument-leak-sentinel",
                                    ),
                                ],
                                "droppedAttributesCount": 0,
                                "events": [],
                                "droppedEventsCount": 0,
                                "links": [],
                                "droppedLinksCount": 0,
                                "status": {
                                    "message": "error-detail-leak-sentinel",
                                    "code": 2,
                                },
                            },
                        ],
                        "schemaUrl": "https://opentelemetry.io/schemas/1.40.0",
                    }
                ],
                "schemaUrl": "https://opentelemetry.io/schemas/1.40.0",
            }
        ]
    }


def _span(payload: dict[str, object]) -> dict[str, Any]:
    resource_spans = payload["resourceSpans"]
    assert isinstance(resource_spans, list)
    resource_span = resource_spans[0]
    assert isinstance(resource_span, dict)
    scope_spans = resource_span["scopeSpans"]
    assert isinstance(scope_spans, list)
    scope_span = scope_spans[0]
    assert isinstance(scope_span, dict)
    spans = scope_span["spans"]
    assert isinstance(spans, list)
    span = spans[0]
    assert isinstance(span, dict)
    return span


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _malformed_payload(case: str) -> dict[str, object]:
    payload = copy.deepcopy(_official_otlp_payload())
    span = _span(payload)
    if case == "short_trace_id":
        span["traceId"] = "1234"
    elif case == "zero_span_id":
        span["spanId"] = "0000000000000000"
    elif case == "named_span_kind":
        span["kind"] = "SPAN_KIND_INTERNAL"
    elif case == "named_status_code":
        status = span["status"]
        assert isinstance(status, dict)
        status["code"] = "STATUS_CODE_OK"
    elif case == "negative_start_time":
        span["startTimeUnixNano"] = "-1"
    elif case == "end_before_start":
        span["endTimeUnixNano"] = "1767225600000000122"
    elif case == "duplicate_attribute":
        attributes = span["attributes"]
        assert isinstance(attributes, list)
        attributes.append(copy.deepcopy(attributes[0]))
    else:
        raise AssertionError(f"unknown malformed fixture case: {case}")
    return payload


def test_official_otlp_json_and_openinference_subset_map_to_privacy_safe_events(
    tmp_path: Path,
) -> None:
    # Arrange
    input_path = tmp_path / "export-trace-service-request.json"
    _write_payload(input_path, _official_otlp_payload())

    # Act
    dataset = validate_file(input_path, input_format="otlp-json")

    # Assert
    assert dataset.input_format == "otlp-json"
    assert dataset.input_record_count == 2
    assert len(dataset.events) == 2
    root, child = dataset.events

    assert root.trace_id == _TRACE_ID.casefold()
    assert root.step_id == _ROOT_SPAN_ID
    assert root.timestamp_ns == 1_767_225_600_000_000_123
    assert root.operation_type == "agent"
    assert root.component == "Planner"
    assert root.duration_ms == Decimal("2")
    assert root.status == "ok"
    assert root.outcome == "success"
    assert dict(root.metadata) == {
        "agent": "Planner",
        "cohort": "synthetic",
        "environment": "integration",
        "service": "journey-api",
    }

    assert child.trace_id == _TRACE_ID.casefold()
    assert child.step_id == _CHILD_SPAN_ID
    assert child.parent_step_id == _ROOT_SPAN_ID
    assert child.timestamp_ns == 1_767_225_600_003_000_456
    assert child.operation_type == "tool"
    assert child.component == "Weather API"
    assert child.duration_ms == Decimal("1.5")
    assert child.status == "error"
    assert child.input_tokens == 7
    assert child.output_tokens == 3
    assert child.cost_usd == Decimal("0.004")
    assert dict(child.metadata) == {
        "environment": "integration",
        "model": "demo-model",
        "service": "journey-api",
    }

    assert len(dataset.traces) == 1
    assert dataset.traces[0].outcome == "success"
    assert dataset.traces[0].outcome_source == "explicit"
    public_output = json.dumps(
        [event.to_dict() for event in dataset.events],
        ensure_ascii=False,
        sort_keys=True,
    )
    for secret in (
        "authorization-leak-sentinel",
        "prompt-leak-sentinel",
        "output-leak-sentinel",
        "private-user",
        "private-session",
        "status-leak-sentinel",
        "error-detail-leak-sentinel",
        "tool-argument-leak-sentinel",
    ):
        assert secret not in public_output


@pytest.mark.parametrize(
    ("case", "error_code", "location_fragment"),
    [
        ("short_trace_id", "invalid_otlp_id", ".traceId"),
        ("zero_span_id", "invalid_otlp_id", ".spanId"),
        ("named_span_kind", "invalid_otlp_span_kind", ".kind"),
        ("named_status_code", "invalid_otlp_status", ".status.code"),
        ("negative_start_time", "invalid_otlp_timestamp", ".startTimeUnixNano"),
        ("end_before_start", "invalid_otlp_duration", ".spans[0]"),
        ("duplicate_attribute", "duplicate_otlp_attribute", ".attributes[8]"),
    ],
)
def test_malformed_otlp_fields_fail_with_actionable_safe_errors(
    tmp_path: Path,
    case: str,
    error_code: str,
    location_fragment: str,
) -> None:
    # Arrange
    input_path = tmp_path / f"{case}.json"
    _write_payload(input_path, _malformed_payload(case))

    # Act
    with pytest.raises(Exception) as exc_info:
        validate_file(input_path, input_format="otlp-json")

    # Assert
    message = str(exc_info.value)
    assert exc_info.type.__name__ == "FormatError"
    assert f"[{error_code}]" in message
    assert location_fragment in message
    assert "Fix:" in message
