"""Unit tests for the complete deterministic analysis payload."""

from __future__ import annotations

import json
from dataclasses import replace
from types import MappingProxyType

from journeygraph.analytics import ANALYSIS_SCHEMA_VERSION, analyze_dataset
from journeygraph.domain import NormalizedDataset


def _by_label(items: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(item["label"]): item for item in items}


def _outcomes(items: object) -> dict[str, int]:
    assert isinstance(items, dict)
    counts = items.get("counts", items)
    assert isinstance(counts, dict)
    return {str(outcome): int(count) for outcome, count in counts.items()}


def test_analysis_matches_manual_totals_paths_and_transitions(
    analytical_dataset: NormalizedDataset,
) -> None:
    # Arrange
    expected_transition_weights = {
        ("router:r", "retrieval:docs"): (4, 4),
        ("retrieval:docs", "model:m"): (3, 3),
        ("retrieval:docs", "retrieval:docs"): (1, 1),
        ("router:r", "tool:search"): (1, 1),
        ("tool:search", "validation:check"): (1, 1),
        ("validation:check", "tool:search"): (1, 1),
        ("router:r", "human:queue"): (1, 1),
    }

    # Act
    analysis = analyze_dataset(analytical_dataset)

    # Assert
    assert analysis["schema_version"] == ANALYSIS_SCHEMA_VERSION == "1.0"
    assert analysis["totals"] == {
        "input_records": 20,
        "events": 18,
        "traces": 6,
        "nodes": 6,
        "transitions": 12,
        "unique_transitions": 7,
        "paths": 5,
        "warnings": 2,
    }
    assert _outcomes(analysis["outcomes"]) == {
        "success": 2,
        "failure": 2,
        "handoff": 1,
        "dropoff": 1,
        "unknown": 0,
    }
    transitions = {
        (str(item["source_label"]), str(item["target_label"])): (
            int(item["weight"]),
            int(item["trace_count"]),
        )
        for item in analysis["transitions"]  # type: ignore[union-attr]
    }
    assert transitions == expected_transition_weights

    paths = analysis["paths"]
    assert isinstance(paths, list)
    shared_path = next(
        path for path in paths if path["labels"] == ["router:r", "retrieval:docs", "model:m"]
    )
    assert shared_path["count"] == 2
    assert shared_path["success_count"] == 1
    assert shared_path["non_success_count"] == 1
    assert shared_path["success_rate"] == 0.5
    assert _outcomes(shared_path["outcomes"]) == {
        "success": 1,
        "failure": 1,
        "handoff": 0,
        "dropoff": 0,
        "unknown": 0,
    }
    for path in paths:
        path_outcomes = _outcomes(path["outcomes"])
        assert path["success_count"] == path_outcomes["success"]
        assert path["non_success_count"] == int(path["count"]) - path_outcomes["success"]
    assert sum(int(path["count"]) for path in paths) == 6


def test_analysis_matches_manual_entries_retries_loops_and_points(
    analytical_dataset: NormalizedDataset,
) -> None:
    # Arrange
    expected_terminals = {
        "human:queue": 1,
        "model:m": 3,
        "retrieval:docs": 1,
        "tool:search": 1,
    }

    # Act
    analysis = analyze_dataset(analytical_dataset)

    # Assert
    assert _by_label(analysis["entries"])["router:r"]["count"] == 6  # type: ignore[arg-type]
    assert {
        label: int(item["count"])
        for label, item in _by_label(analysis["terminals"]).items()  # type: ignore[arg-type]
    } == expected_terminals
    retries = analysis["retries"]
    assert isinstance(retries, list)
    assert len(retries) == 1
    assert retries[0] == {
        "node_id": retries[0]["node_id"],
        "label": "retrieval:docs",
        "node_ids": [retries[0]["node_id"]],
        "labels": ["retrieval:docs"],
        "count": 1,
        "trace_count": 1,
    }

    loops = analysis["loops"]
    assert isinstance(loops, list)
    assert len(loops) == 1
    assert loops[0]["labels"] == ["tool:search", "validation:check", "tool:search"]
    assert loops[0]["node_ids"][0] == loops[0]["node_ids"][-1]
    assert loops[0]["count"] == 1
    assert loops[0]["trace_count"] == 1

    failures = _by_label(analysis["failure_points"])  # type: ignore[arg-type]
    assert {
        label: (
            int(item["count"]),
            int(item["error_event_count"]),
            int(item["terminal_failure_count"]),
        )
        for label, item in failures.items()
    } == {
        "model:m": (1, 1, 1),
        "retrieval:docs": (1, 1, 0),
        "tool:search": (1, 1, 1),
    }
    dropoffs = _by_label(analysis["dropoff_points"])  # type: ignore[arg-type]
    assert dropoffs["retrieval:docs"] == {
        "node_id": dropoffs["retrieval:docs"]["node_id"],
        "label": "retrieval:docs",
        "count": 1,
        "explicit_count": 0,
        "inferred_count": 1,
        "outcome_sources": [{"source": "missing", "count": 1}],
    }

    comparison = analysis["path_comparison"]
    assert comparison == [
        {"group": "success", "trace_count": 2, "path_count": 2},
        {
            "group": "non_success",
            "trace_count": 4,
            "path_count": 4,
            "outcomes": {
                "success": 0,
                "failure": 2,
                "handoff": 1,
                "dropoff": 1,
                "unknown": 0,
            },
            "outcome_rates": {
                "success": 0.0,
                "failure": 0.5,
                "handoff": 0.25,
                "dropoff": 0.25,
                "unknown": 0.0,
            },
        },
    ]


def test_analysis_matches_manual_metric_and_cohort_oracles(
    analytical_dataset: NormalizedDataset,
) -> None:
    # Arrange
    expected_cost = {
        "count": 4,
        "missing_count": 14,
        "sum": 0.05,
        "min": 0.005,
        "max": 0.02,
        "mean": 0.0125,
        "p50": 0.01,
        "p95": 0.02,
        "percentile_method": "nearest_rank",
    }

    # Act
    analysis = analyze_dataset(analytical_dataset)

    # Assert
    metrics = analysis["metrics"]
    assert isinstance(metrics, dict)
    assert metrics["duration_ms"] == {
        "count": 18,
        "missing_count": 0,
        "sum": 370,
        "min": 5,
        "max": 50,
        "mean": 20.555555555555557,
        "p50": 20,
        "p95": 50,
        "percentile_method": "nearest_rank",
    }
    assert metrics["input_tokens"] == {
        "count": 3,
        "missing_count": 15,
        "sum": 280,
        "min": 80,
        "max": 100,
        "mean": 93.33333333333333,
        "p50": 100,
        "p95": 100,
        "percentile_method": "nearest_rank",
    }
    assert metrics["total_tokens"] == {
        "count": 3,
        "missing_count": 15,
        "sum": 330,
        "min": 100,
        "max": 120,
        "mean": 110,
        "p50": 110,
        "p95": 120,
        "percentile_method": "nearest_rank",
    }
    assert metrics["cost_usd"] == expected_cost

    cohorts = analysis["cohorts"]
    assert isinstance(cohorts, dict)
    assert cohorts["key"] == "cohort"
    assert cohorts["missing_trace_count"] == 1
    assert cohorts["conflicting_trace_count"] == 0
    items = {item["value"]: item for item in cohorts["items"]}  # type: ignore[union-attr]
    assert {value: int(item["trace_count"]) for value, item in items.items()} == {
        None: 1,
        "alpha": 3,
        "beta": 2,
    }
    assert _outcomes(items["alpha"]["outcomes"])["success"] == 2
    assert _outcomes(items["beta"]["outcomes"])["handoff"] == 1


def test_analysis_is_json_ready_sorted_and_input_order_invariant(
    analytical_dataset: NormalizedDataset,
) -> None:
    # Arrange
    permuted = NormalizedDataset(
        events=tuple(reversed(analytical_dataset.events)),
        traces=tuple(reversed(analytical_dataset.traces)),
        warnings=tuple(reversed(analytical_dataset.warnings)),
        input_format=analytical_dataset.input_format,
        input_record_count=analytical_dataset.input_record_count,
    )

    # Act
    original = analyze_dataset(analytical_dataset)
    shuffled = analyze_dataset(permuted)
    encoded = json.dumps(original, allow_nan=False, ensure_ascii=False, sort_keys=True)

    # Assert
    assert original == shuffled
    assert encoded.startswith("{")
    assert [warning["code"] for warning in original["warnings"]] == [  # type: ignore[union-attr]
        "a_private",
        "z_late",
    ]
    assert [node["id"] for node in original["nodes"]] == sorted(  # type: ignore[union-attr]
        node["id"]
        for node in original["nodes"]  # type: ignore[union-attr]
    )


def test_cohort_conflict_is_reported_without_mutating_metadata(
    analytical_dataset: NormalizedDataset,
) -> None:
    # Arrange
    first_trace = analytical_dataset.traces[0]
    conflicting_event = replace(
        first_trace.events[-1], metadata=MappingProxyType({"cohort": "omega"})
    )
    conflicting_trace = replace(first_trace, events=(*first_trace.events[:-1], conflicting_event))
    dataset = NormalizedDataset(
        events=conflicting_trace.events,
        traces=(conflicting_trace,),
        warnings=(),
        input_format="jsonl",
        input_record_count=3,
    )

    # Act
    analysis = analyze_dataset(dataset)

    # Assert
    cohorts = analysis["cohorts"]
    assert isinstance(cohorts, dict)
    assert cohorts["conflicting_trace_count"] == 1
    items = cohorts["items"]
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["value"] == "alpha"
    assert conflicting_event.metadata == {"cohort": "omega"}


def test_cohort_analysis_can_be_disabled_explicitly(
    analytical_dataset: NormalizedDataset,
) -> None:
    # Arrange
    expected = {
        "key": None,
        "missing_trace_count": 6,
        "conflicting_trace_count": 0,
        "items": [],
    }

    # Act
    analysis = analyze_dataset(analytical_dataset, cohort_key=None)

    # Assert
    assert analysis["config"] == {"cohort_key": None}
    assert analysis["cohorts"] == expected


def test_retries_and_loops_require_the_same_component_as_well_as_operation(
    analytical_dataset: NormalizedDataset,
) -> None:
    # Arrange
    retry_trace = analytical_dataset.traces[2]
    changed_retry_event = replace(retry_trace.events[2], component="cache")
    retry_trace = replace(
        retry_trace,
        events=(*retry_trace.events[:2], changed_retry_event, retry_trace.events[3]),
    )
    loop_trace = analytical_dataset.traces[3]
    changed_loop_event = replace(loop_trace.events[-1], component="database")
    loop_trace = replace(loop_trace, events=(*loop_trace.events[:-1], changed_loop_event))
    traces = (retry_trace, loop_trace)
    dataset = NormalizedDataset(
        events=tuple(event for trace in traces for event in trace.events),
        traces=traces,
        warnings=(),
        input_format="jsonl",
        input_record_count=8,
    )

    # Act
    analysis = analyze_dataset(dataset)

    # Assert
    assert analysis["retries"] == []
    assert analysis["loops"] == []
