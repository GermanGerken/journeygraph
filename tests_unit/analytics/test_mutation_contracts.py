"""Regression contracts for semantically important analytics mutation survivors."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib.resources import files
from types import MappingProxyType
from typing import Literal

from jsonschema import Draft202012Validator

from journeygraph.analytics import analyze_dataset
from journeygraph.domain import CanonicalEvent, Issue, NormalizedDataset, Trace

EventStatus = Literal["unset", "ok", "error"]
TraceOutcome = Literal["success", "failure", "handoff", "dropoff", "unknown"]
OutcomeSource = Literal["explicit", "terminal_status", "missing"]

OUTCOME_KEYS = {"success", "failure", "handoff", "dropoff", "unknown"}
METRIC_SUMMARY_KEYS = {
    "count",
    "missing_count",
    "sum",
    "min",
    "max",
    "mean",
    "p50",
    "p95",
    "percentile_method",
}


def _event(
    trace_id: str,
    index: int,
    operation_type: str,
    component: str,
    *,
    status: EventStatus = "ok",
    outcome: TraceOutcome | None = None,
    cohort: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> CanonicalEvent:
    metadata = {} if cohort is None else {"cohort": cohort}
    return CanonicalEvent(
        trace_id=trace_id,
        step_id=f"{trace_id}-{index}",
        parent_step_id=None,
        timestamp=datetime(2026, 7, 21, tzinfo=UTC) + timedelta(microseconds=index),
        operation_type=operation_type,
        component=component,
        duration_ms=Decimal(index + 1),
        status=status,
        outcome=outcome,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=None,
        metadata=MappingProxyType(metadata),
    )


def _trace(
    trace_id: str,
    events: tuple[CanonicalEvent, ...],
    outcome: TraceOutcome,
    outcome_source: OutcomeSource,
) -> Trace:
    return Trace(
        trace_id=trace_id,
        events=events,
        outcome=outcome,
        outcome_source=outcome_source,
    )


def _dataset(traces: tuple[Trace, ...], *, warnings: tuple[Issue, ...] = ()) -> NormalizedDataset:
    events = tuple(event for trace in traces for event in trace.events)
    return NormalizedDataset(
        events=events,
        traces=traces,
        warnings=warnings,
        input_format="jsonl",
        input_record_count=len(events),
    )


def _multi_trace_dataset() -> NormalizedDataset:
    failure_one_events = (
        _event("failure-1", 0, "planner", "plan", cohort="alpha"),
        _event("failure-1", 1, "planner", "plan", cohort="alpha"),
        _event("failure-1", 2, "planner", "plan", cohort="alpha"),
        _event("failure-1", 3, "tool", "search", cohort="alpha"),
        _event("failure-1", 4, "planner", "plan", cohort="alpha"),
        _event(
            "failure-1",
            5,
            "outcome",
            "end",
            status="error",
            outcome="failure",
            cohort="omega",
        ),
    )
    failure_two_events = (
        _event("failure-2", 0, "planner", "plan", cohort="alpha"),
        _event("failure-2", 1, "planner", "plan", cohort="alpha"),
        _event("failure-2", 2, "tool", "search", cohort="alpha"),
        _event("failure-2", 3, "planner", "plan", cohort="alpha"),
        _event(
            "failure-2",
            4,
            "outcome",
            "end",
            status="error",
            outcome="failure",
            cohort="omega",
        ),
    )
    explicit_dropoff_events = (
        _event("dropoff-1", 0, "request", "start", cohort="beta"),
        _event("dropoff-1", 1, "tool", "work", cohort="beta"),
        _event(
            "dropoff-1",
            2,
            "outcome",
            "end",
            outcome="dropoff",
            cohort="beta",
        ),
    )
    inferred_dropoff_events = (
        _event("dropoff-2", 0, "request", "start", cohort="beta"),
        _event("dropoff-2", 1, "tool", "work", cohort="beta"),
        _event("dropoff-2", 2, "outcome", "end", cohort="beta"),
    )
    second_inferred_dropoff_events = (
        _event("dropoff-3", 0, "request", "start", cohort="beta"),
        _event("dropoff-3", 1, "tool", "work", cohort="beta"),
        _event("dropoff-3", 2, "outcome", "end", cohort="beta"),
    )
    traces = (
        _trace("failure-1", failure_one_events, "failure", "explicit"),
        _trace("failure-2", failure_two_events, "failure", "explicit"),
        _trace("dropoff-1", explicit_dropoff_events, "dropoff", "explicit"),
        _trace("dropoff-2", inferred_dropoff_events, "dropoff", "missing"),
        _trace("dropoff-3", second_inferred_dropoff_events, "dropoff", "missing"),
    )
    warning = Issue(
        severity="warning",
        code="contract_warning",
        location="record 1",
        message="A synthetic warning was retained.",
        hint="Inspect the synthetic fixture.",
    )
    return _dataset(traces, warnings=(warning,))


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _items(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return value


def _by_label(value: object) -> dict[str, dict[str, object]]:
    return {str(item["label"]): item for item in _items(value)}


def test_empty_dataset_reports_zero_outcome_rates() -> None:
    # Arrange
    dataset = NormalizedDataset(
        events=(),
        traces=(),
        warnings=(),
        input_format="jsonl",
        input_record_count=0,
    )

    # Act
    analysis = analyze_dataset(dataset)

    # Assert
    outcomes = _mapping(analysis["outcomes"])
    assert outcomes["counts"] == dict.fromkeys(OUTCOME_KEYS, 0)
    assert outcomes["rates"] == dict.fromkeys(OUTCOME_KEYS, 0.0)
    comparison = _items(analysis["path_comparison"])
    assert comparison == [
        {"group": "success", "trace_count": 0, "path_count": 0},
        {
            "group": "non_success",
            "trace_count": 0,
            "path_count": 0,
            "outcomes": dict.fromkeys(OUTCOME_KEYS, 0),
            "outcome_rates": dict.fromkeys(OUTCOME_KEYS, 0.0),
        },
    ]
    assert analysis["paths"] == []
    assert analysis["cohorts"] == {
        "key": "cohort",
        "missing_trace_count": 0,
        "conflicting_trace_count": 0,
        "items": [],
    }


def test_failure_only_path_has_zero_success_count() -> None:
    # Arrange
    events = (
        _event("failure-only", 0, "request", "start"),
        _event("failure-only", 1, "outcome", "end", outcome="failure"),
    )
    dataset = _dataset((_trace("failure-only", events, "failure", "explicit"),))

    # Act
    analysis = analyze_dataset(dataset)

    # Assert
    paths = _items(analysis["paths"])
    assert len(paths) == 1
    assert paths[0]["count"] == 1
    assert paths[0]["outcomes"] == {
        "success": 0,
        "failure": 1,
        "handoff": 0,
        "dropoff": 0,
        "unknown": 0,
    }
    assert paths[0]["success_count"] == 0
    assert paths[0]["non_success_count"] == 1
    assert paths[0]["success_rate"] == 0.0


def test_multi_trace_aggregates_preserve_occurrence_and_trace_semantics() -> None:
    # Arrange
    dataset = _multi_trace_dataset()

    # Act
    analysis = analyze_dataset(dataset)

    # Assert
    retries = _by_label(analysis["retries"])
    assert retries["planner:plan"]["count"] == 3
    assert retries["planner:plan"]["trace_count"] == 2

    loops = _items(analysis["loops"])
    assert len(loops) == 1
    assert loops[0]["labels"] == ["planner:plan", "tool:search", "planner:plan"]
    assert loops[0]["count"] == 2
    assert loops[0]["trace_count"] == 2

    failures = _by_label(analysis["failure_points"])
    assert failures["outcome:end"]["count"] == 2
    assert failures["outcome:end"]["trace_count"] == 2
    assert failures["outcome:end"]["error_event_count"] == 2
    assert failures["outcome:end"]["terminal_failure_count"] == 2

    dropoffs = _by_label(analysis["dropoff_points"])
    assert dropoffs["outcome:end"]["count"] == 3
    assert dropoffs["outcome:end"]["explicit_count"] == 1
    assert dropoffs["outcome:end"]["inferred_count"] == 2
    assert dropoffs["outcome:end"]["outcome_sources"] == [
        {"source": "explicit", "count": 1},
        {"source": "missing", "count": 2},
    ]

    cohorts = _mapping(analysis["cohorts"])
    assert cohorts["missing_trace_count"] == 0
    assert cohorts["conflicting_trace_count"] == 2
    cohort_items = {item["value"]: item for item in _items(cohorts["items"])}
    assert cohort_items["alpha"]["trace_count"] == 2
    assert cohort_items["alpha"]["event_count"] == 11
    assert cohort_items["alpha"]["path_count"] == 2
    assert cohort_items["alpha"]["outcomes"] == {
        "success": 0,
        "failure": 2,
        "handoff": 0,
        "dropoff": 0,
        "unknown": 0,
    }
    assert cohort_items["alpha"]["outcome_rates"] == {
        "success": 0.0,
        "failure": 1.0,
        "handoff": 0.0,
        "dropoff": 0.0,
        "unknown": 0.0,
    }
    assert cohort_items["beta"]["trace_count"] == 3
    assert cohort_items["beta"]["event_count"] == 9
    assert cohort_items["beta"]["path_count"] == 1
    assert cohort_items["beta"]["outcomes"] == {
        "success": 0,
        "failure": 0,
        "handoff": 0,
        "dropoff": 3,
        "unknown": 0,
    }


def test_total_tokens_treats_one_missing_side_as_zero() -> None:
    # Arrange
    events = (
        _event("tokens", 0, "model", "input-only", input_tokens=7),
        _event("tokens", 1, "model", "output-only", output_tokens=11),
        _event("tokens", 2, "tool", "unmetered", outcome="success"),
    )
    dataset = _dataset((_trace("tokens", events, "success", "explicit"),))

    # Act
    analysis = analyze_dataset(dataset)

    # Assert
    metrics = _mapping(analysis["metrics"])
    assert metrics["total_tokens"] == {
        "count": 2,
        "missing_count": 1,
        "sum": 18,
        "min": 7,
        "max": 11,
        "mean": 9,
        "p50": 7,
        "p95": 11,
        "percentile_method": "nearest_rank",
    }


def test_analysis_matches_packaged_schema_and_public_key_contract() -> None:
    # Arrange
    dataset = _multi_trace_dataset()
    schema = json.loads(
        files("journeygraph.schemas")
        .joinpath("analysis-v1.schema.json")
        .read_text(encoding="utf-8")
    )

    # Act
    analysis = analyze_dataset(dataset, tool_version="contract-test")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(analysis)

    # Assert
    assert set(analysis) == {
        "schema_version",
        "tool_version",
        "config",
        "totals",
        "outcomes",
        "nodes",
        "transitions",
        "entries",
        "terminals",
        "paths",
        "retries",
        "loops",
        "failure_points",
        "dropoff_points",
        "path_comparison",
        "cohorts",
        "metrics",
        "warnings",
    }
    assert set(_mapping(analysis["config"])) == {"cohort_key"}
    assert set(_mapping(analysis["totals"])) == {
        "input_records",
        "events",
        "traces",
        "nodes",
        "transitions",
        "unique_transitions",
        "paths",
        "warnings",
    }
    outcome_summary = _mapping(analysis["outcomes"])
    assert set(outcome_summary) == {"counts", "rates"}
    assert set(_mapping(outcome_summary["counts"])) == OUTCOME_KEYS
    assert set(_mapping(outcome_summary["rates"])) == OUTCOME_KEYS

    assert set(_items(analysis["nodes"])[0]) == {
        "id",
        "label",
        "operation_type",
        "component",
        "event_count",
        "trace_count",
    }
    assert set(_items(analysis["transitions"])[0]) == {
        "source",
        "target",
        "source_label",
        "target_label",
        "weight",
        "trace_count",
    }
    assert set(_items(analysis["entries"])[0]) == {"node_id", "label", "count"}
    assert set(_items(analysis["terminals"])[0]) == {"node_id", "label", "count"}
    assert set(_items(analysis["paths"])[0]) == {
        "path_id",
        "node_ids",
        "labels",
        "count",
        "rate",
        "outcomes",
        "outcome_rates",
        "success_count",
        "non_success_count",
        "success_rate",
    }
    assert set(_items(analysis["retries"])[0]) == {
        "node_id",
        "label",
        "node_ids",
        "labels",
        "count",
        "trace_count",
    }
    assert set(_items(analysis["loops"])[0]) == {
        "loop_id",
        "node_ids",
        "labels",
        "count",
        "trace_count",
    }
    assert set(_items(analysis["failure_points"])[0]) == {
        "node_id",
        "label",
        "count",
        "trace_count",
        "error_event_count",
        "terminal_failure_count",
    }
    dropoff = _items(analysis["dropoff_points"])[0]
    assert set(dropoff) == {
        "node_id",
        "label",
        "count",
        "explicit_count",
        "inferred_count",
        "outcome_sources",
    }
    assert set(_items(dropoff["outcome_sources"])[0]) == {"source", "count"}

    comparison = _items(analysis["path_comparison"])
    assert set(comparison[0]) == {"group", "trace_count", "path_count"}
    assert set(comparison[1]) == {
        "group",
        "trace_count",
        "path_count",
        "outcomes",
        "outcome_rates",
    }
    cohorts = _mapping(analysis["cohorts"])
    assert set(cohorts) == {"key", "missing_trace_count", "conflicting_trace_count", "items"}
    cohort = _items(cohorts["items"])[0]
    assert set(cohort) == {
        "cohort_id",
        "key",
        "value",
        "trace_count",
        "event_count",
        "path_count",
        "outcomes",
        "outcome_rates",
        "metrics",
    }
    metrics = _mapping(analysis["metrics"])
    assert set(metrics) == {
        "scope",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_usd",
    }
    for metric_name in ("duration_ms", "input_tokens", "output_tokens", "total_tokens", "cost_usd"):
        assert set(_mapping(metrics[metric_name])) == METRIC_SUMMARY_KEYS
    assert set(_items(analysis["warnings"])[0]) == {
        "code",
        "severity",
        "location",
        "message",
        "hint",
    }
