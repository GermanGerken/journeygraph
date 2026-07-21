from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

from journeygraph.domain.models import CanonicalEvent, Issue, Trace, decimal_to_json_number


def test_event_exposes_stable_category_tokens_and_canonical_payload() -> None:
    # Arrange
    event = CanonicalEvent(
        trace_id="trace-1",
        step_id="step-1",
        parent_step_id="root",
        timestamp=datetime(2026, 7, 21, 12, 30, 1, 123456, tzinfo=UTC),
        operation_type="tool",
        component="Поиск 🔎",
        duration_ms=Decimal("12.50"),
        status="ok",
        outcome="success",
        input_tokens=10,
        output_tokens=5,
        cost_usd=Decimal("0.00125"),
        metadata=MappingProxyType({"service": "demo", "cohort": "a"}),
        timestamp_ns=1_784_637_001_123_456_123,
    )

    # Act
    payload = event.to_dict()

    # Assert
    assert event.category == ("tool", "Поиск 🔎")
    assert event.label == "tool:Поиск 🔎"
    assert event.total_tokens == 15
    assert event.sort_key == (1_784_637_001_123_456_123, "step-1")
    assert payload == {
        "schema_version": "1.0",
        "trace_id": "trace-1",
        "step_id": "step-1",
        "parent_step_id": "root",
        "timestamp": "2026-07-21T12:30:01.123456123Z",
        "operation_type": "tool",
        "component": "Поиск 🔎",
        "duration_ms": 12.5,
        "status": "ok",
        "outcome": "success",
        "input_tokens": 10,
        "output_tokens": 5,
        "cost_usd": 0.00125,
        "metadata": {"cohort": "a", "service": "demo"},
    }


def test_optional_metrics_and_trace_labels_remain_explicit() -> None:
    # Arrange
    event = CanonicalEvent(
        trace_id="trace-1",
        step_id="step-1",
        parent_step_id=None,
        timestamp=datetime(2026, 7, 21, tzinfo=UTC),
        operation_type="request",
        component="entry",
        duration_ms=Decimal("2"),
        status="unset",
        outcome=None,
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
    )
    trace = Trace("trace-1", (event,), "dropoff", "missing")

    # Act
    payload = event.to_dict()

    # Assert
    assert event.total_tokens is None
    assert trace.labels == ("request:entry",)
    assert payload == {
        "schema_version": "1.0",
        "trace_id": "trace-1",
        "step_id": "step-1",
        "timestamp": "2026-07-21T00:00:00.000000Z",
        "operation_type": "request",
        "component": "entry",
        "duration_ms": 2,
        "status": "unset",
    }


def test_issue_and_decimal_helpers_match_public_contract() -> None:
    # Arrange
    issue = Issue("error", "bad_field", "line 2.x", "x is invalid", "provide x")

    # Act
    formatted = issue.format()
    payload = issue.to_dict()

    # Assert
    assert formatted == "[bad_field] line 2.x: x is invalid Fix: provide x"
    assert payload == {
        "severity": "error",
        "code": "bad_field",
        "location": "line 2.x",
        "message": "x is invalid",
        "hint": "provide x",
    }
    assert decimal_to_json_number(Decimal("7")) == 7
    assert decimal_to_json_number(Decimal("7.25")) == 7.25
