"""Manually specified analytics fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest

from journeygraph.domain import CanonicalEvent, Issue, NormalizedDataset, Trace


def event(
    trace_id: str,
    step: int,
    operation_type: str,
    component: str,
    duration_ms: str,
    *,
    status: str = "ok",
    outcome: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: str | None = None,
    cohort: str | None = None,
) -> CanonicalEvent:
    metadata = {} if cohort is None else {"cohort": cohort}
    return CanonicalEvent(
        trace_id=trace_id,
        step_id=f"s{step}",
        parent_step_id=None,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=step),
        operation_type=operation_type,
        component=component,
        duration_ms=Decimal(duration_ms),
        status=status,  # type: ignore[arg-type]
        outcome=outcome,  # type: ignore[arg-type]
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=Decimal(cost_usd) if cost_usd is not None else None,
        metadata=MappingProxyType(metadata),
    )


@pytest.fixture
def analytical_dataset() -> NormalizedDataset:
    """Return six traces with independently calculated aggregate oracles."""

    trace_one_events = (
        event("t1", 1, "router", "r", "10", cohort="alpha"),
        event("t1", 2, "retrieval", "docs", "20", cohort="alpha"),
        event(
            "t1",
            3,
            "model",
            "m",
            "30",
            outcome="success",
            input_tokens=100,
            output_tokens=20,
            cost_usd="0.01",
            cohort="alpha",
        ),
    )
    trace_two_events = (
        event("t2", 1, "router", "r", "10", cohort="alpha"),
        event("t2", 2, "retrieval", "docs", "20", cohort="alpha"),
        event(
            "t2",
            3,
            "model",
            "m",
            "30",
            status="error",
            outcome="failure",
            input_tokens=100,
            output_tokens=10,
            cost_usd="0.02",
            cohort="alpha",
        ),
    )
    trace_three_events = (
        event("t3", 1, "router", "r", "10", cohort="alpha"),
        event(
            "t3",
            2,
            "retrieval",
            "docs",
            "20",
            status="error",
            cohort="alpha",
        ),
        event("t3", 3, "retrieval", "docs", "5", cohort="alpha"),
        event(
            "t3",
            4,
            "model",
            "m",
            "30",
            outcome="success",
            input_tokens=80,
            output_tokens=20,
            cost_usd="0.015",
            cohort="alpha",
        ),
    )
    trace_four_events = (
        event("t4", 1, "router", "r", "10", cohort="beta"),
        event("t4", 2, "tool", "search", "40", cohort="beta"),
        event("t4", 3, "validation", "check", "5", cohort="beta"),
        event(
            "t4",
            4,
            "tool",
            "search",
            "40",
            status="error",
            outcome="failure",
            cost_usd="0.005",
            cohort="beta",
        ),
    )
    trace_five_events = (
        event("t5", 1, "router", "r", "10"),
        event("t5", 2, "retrieval", "docs", "20"),
    )
    trace_six_events = (
        event("t6", 1, "router", "r", "10", cohort="beta"),
        event("t6", 2, "human", "queue", "50", outcome="handoff", cohort="beta"),
    )
    traces = (
        Trace("t1", trace_one_events, "success", "explicit"),
        Trace("t2", trace_two_events, "failure", "explicit"),
        Trace("t3", trace_three_events, "success", "explicit"),
        Trace("t4", trace_four_events, "failure", "explicit"),
        Trace("t5", trace_five_events, "dropoff", "missing"),
        Trace("t6", trace_six_events, "handoff", "explicit"),
    )
    events = tuple(item for trace in traces for item in trace.events)
    warnings = (
        Issue("warning", "z_late", "line 9", "Rows were reordered.", "Sort input."),
        Issue(
            "warning",
            "a_private",
            "line 2",
            "Metadata was excluded.",
            "Use operational metadata only.",
        ),
    )
    return NormalizedDataset(
        events=events,
        traces=traces,
        warnings=warnings,
        input_format="jsonl",
        input_record_count=20,
    )
