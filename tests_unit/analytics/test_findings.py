"""Unit tests for per-category statistics and ranked association-only findings."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from journeygraph.analytics import analyze_dataset, build_findings, wilson_interval
from journeygraph.domain import NormalizedDataset


def _by_label(items: object) -> dict[str, Mapping[str, object]]:
    assert isinstance(items, list)
    return {str(item["label"]): item for item in items}


def _counts(summary: object) -> dict[str, int]:
    assert isinstance(summary, Mapping)
    counts = summary["counts"]
    assert isinstance(counts, Mapping)
    return {str(key): int(value) for key, value in counts.items()}


def _node(
    label: str,
    *,
    events: int = 10,
    traces: int = 10,
    errors: int = 0,
    outcomes: Mapping[str, int] | None = None,
    duration: float = 0,
    duration_count: int | None = None,
    cost: float = 0,
    cost_count: int = 0,
) -> dict[str, object]:
    counts = {"success": 0, "failure": 0, "handoff": 0, "dropoff": 0, "unknown": 0}
    counts.update(outcomes or {})
    present_duration = events if duration_count is None else duration_count
    return {
        "id": (label.encode().hex() * 64)[:64],
        "label": label,
        "event_count": events,
        "trace_count": traces,
        "error_event_count": errors,
        "metrics": {
            "duration_ms": {
                "count": present_duration,
                "missing_count": events - present_duration,
                "sum": duration,
            },
            "total_tokens": {"count": 0, "missing_count": events, "sum": 0},
            "cost_usd": {"count": cost_count, "missing_count": events - cost_count, "sum": cost},
        },
        "trace_outcomes": {"counts": counts},
    }


def _report(
    nodes: list[dict[str, object]],
    *,
    outcomes: Mapping[str, int] | None = None,
    traces: int = 20,
    retries: list[dict[str, object]] | None = None,
    warnings: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    counts = {"success": 0, "failure": 0, "handoff": 0, "dropoff": 0, "unknown": 0}
    counts.update(outcomes or {})
    return {
        "totals": {"traces": traces},
        "outcomes": {"counts": counts},
        "nodes": nodes,
        "retries": retries or [],
        "warnings": warnings or [],
    }


def _kinds(findings: Mapping[str, object]) -> list[tuple[str, str]]:
    items = findings["items"]
    assert isinstance(items, list)
    return [(str(item["kind"]), str(item["label"])) for item in items]


def test_nodes_and_transitions_carry_hand_computed_statistics(
    analytical_dataset: NormalizedDataset,
) -> None:
    # Arrange
    expected_retrieval_outcomes = {
        "success": 2,
        "failure": 1,
        "handoff": 0,
        "dropoff": 1,
        "unknown": 0,
    }

    # Act
    analysis = analyze_dataset(analytical_dataset)

    # Assert
    nodes = _by_label(analysis["nodes"])
    retrieval = nodes["retrieval:docs"]
    assert retrieval["error_event_count"] == 1
    retrieval_metrics = retrieval["metrics"]
    assert isinstance(retrieval_metrics, Mapping)
    assert retrieval_metrics["duration_ms"]["sum"] == 85
    assert retrieval_metrics["duration_ms"]["count"] == 5
    assert _counts(retrieval["trace_outcomes"]) == expected_retrieval_outcomes
    assert retrieval["trace_outcomes"]["rates"]["success"] == 0.5
    model_metrics = nodes["model:m"]["metrics"]
    assert isinstance(model_metrics, Mapping)
    assert model_metrics["total_tokens"]["sum"] == 330
    assert model_metrics["cost_usd"]["sum"] == 0.045
    tool_metrics = nodes["tool:search"]["metrics"]
    assert isinstance(tool_metrics, Mapping)
    assert tool_metrics["cost_usd"]["count"] == 1
    assert tool_metrics["cost_usd"]["missing_count"] == 1
    assert nodes["router:r"]["error_event_count"] == 0

    transitions = {
        (str(edge["source_label"]), str(edge["target_label"])): edge
        for edge in analysis["transitions"]  # type: ignore[union-attr]
    }
    assert _counts(transitions[("retrieval:docs", "model:m")]["trace_outcomes"]) == {
        "success": 2,
        "failure": 1,
        "handoff": 0,
        "dropoff": 0,
        "unknown": 0,
    }
    assert _counts(transitions[("router:r", "retrieval:docs")]["trace_outcomes"]) == (
        expected_retrieval_outcomes
    )


def test_analysis_findings_match_independent_oracle(
    analytical_dataset: NormalizedDataset,
) -> None:
    # Arrange: 6 known outcomes, 2 successes; model:m is visited by t1-t3 (2 successes).

    # Act
    findings = analyze_dataset(analytical_dataset)["findings"]

    # Assert
    assert isinstance(findings, Mapping)
    assert findings["config"] == {"min_support": 3, "max_items": 10}
    assert _kinds(findings) == [
        ("outcome_association", "model:m"),
        ("error_hotspot", "model:m"),
        ("error_hotspot", "retrieval:docs"),
        ("cost_concentration", "model:m"),
    ]
    items = findings["items"]
    assert isinstance(items, list)
    association, model_errors, retrieval_errors, cost = items
    assert association["value"] == pytest.approx(2 / 3)
    assert association["baseline"] == 0.0
    assert association["support"] == 3
    assert association["baseline_support"] == 3
    assert association["support_level"] == "low"
    assert "association, not a cause" in str(association["statement"])
    assert model_errors["baseline"] == pytest.approx(3 / 18)
    assert retrieval_errors["value"] == 0.2
    assert cost["value"] == pytest.approx(0.9)
    assert cost["interval"] is None


def test_min_support_changes_eligibility(analytical_dataset: NormalizedDataset) -> None:
    # Act
    relaxed = analyze_dataset(analytical_dataset, min_support=2)["findings"]
    strict = analyze_dataset(analytical_dataset, min_support=50)["findings"]

    # Assert
    assert isinstance(relaxed, Mapping) and isinstance(strict, Mapping)
    assert ("outcome_association", "retrieval:docs") in _kinds(relaxed)
    assert strict["items"] == []
    assert strict["config"] == {"min_support": 50, "max_items": 10}


@pytest.mark.parametrize("invalid", [0, -1, True, 2.5])
def test_min_support_rejects_non_positive_integers(invalid: object) -> None:
    with pytest.raises(ValueError, match="min_support"):
        build_findings(_report([]), min_support=invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("successes", "total", "low", "high"),
    [(0, 10, 0.0, 0.2775), (5, 10, 0.2366, 0.7634), (2, 3, 0.2077, 0.9385), (10, 10, 0.7225, 1)],
)
def test_wilson_interval_matches_published_reference_values(
    successes: int, total: int, low: float, high: float
) -> None:
    # Act
    interval = wilson_interval(successes, total)

    # Assert
    assert interval is not None
    assert interval["method"] == "wilson"
    assert interval["level"] == 0.95
    assert interval["low"] == pytest.approx(low, abs=5e-5)
    assert interval["high"] == pytest.approx(high, abs=5e-5)


def test_wilson_interval_handles_empty_and_invalid_samples() -> None:
    assert wilson_interval(0, 0) is None
    with pytest.raises(ValueError):
        wilson_interval(4, 3)


@pytest.mark.parametrize(("node_success", "expected"), [(7, True), (6, False)])
def test_outcome_association_threshold_is_inclusive(node_success: int, expected: bool) -> None:
    # Arrange: 10 visiting known traces versus 10 non-visiting traces with 5 successes;
    # 7/10 versus 5/10 is exactly the 0.20 threshold and 6/10 is below it.
    node = _node("tool:x", outcomes={"success": node_success, "failure": 10 - node_success})
    report = _report(
        [node, _node("router:r", traces=20)],
        outcomes={"success": node_success + 5, "failure": 15 - node_success},
    )

    # Act
    kinds = _kinds(build_findings(report))

    # Assert
    assert (("outcome_association", "tool:x") in kinds) is expected


def test_outcome_association_excludes_unknown_outcomes_and_says_so() -> None:
    # Arrange: 4 unknown visiting traces must not count as non-success.
    node = _node("tool:x", traces=10, outcomes={"success": 6, "unknown": 4})
    report = _report([node], outcomes={"success": 7, "failure": 9, "unknown": 4})

    # Act
    items = build_findings(report)["items"]

    # Assert
    assert isinstance(items, list)
    association = items[0]
    assert association["kind"] == "outcome_association"
    assert association["value"] == 1.0
    assert association["support"] == 6
    assert association["baseline"] == 0.1
    assert "4 visiting trace(s) with an unknown outcome were excluded" in str(
        association["statement"]
    )


def test_outcome_association_requires_known_outcomes_on_both_sides() -> None:
    # Arrange
    everyone = _node("router:r", traces=6, outcomes={"success": 3, "failure": 3})
    unknown_only = _node("tool:y", traces=5, outcomes={"unknown": 5})
    report = _report([everyone, unknown_only], outcomes={"success": 3, "failure": 3, "unknown": 5})

    # Act / Assert
    assert build_findings(report)["items"] == []


@pytest.mark.parametrize(("errors", "expected"), [(2, True), (1, False)])
def test_error_hotspot_threshold(errors: int, expected: bool) -> None:
    # Arrange
    report = _report([_node("tool:x", events=10, errors=errors), _node("router:r", events=10)])

    # Act
    kinds = _kinds(build_findings(report))

    # Assert
    assert (("error_hotspot", "tool:x") in kinds) is expected


def test_error_hotspot_respects_min_support() -> None:
    report = _report([_node("tool:x", events=2, errors=2), _node("router:r", events=8)])
    assert _kinds(build_findings(report)) == []
    assert _kinds(build_findings(report, min_support=2)) == [("error_hotspot", "tool:x")]


@pytest.mark.parametrize(("duration", "expected"), [(25, True), (24, False)])
def test_duration_concentration_threshold(duration: float, expected: bool) -> None:
    # Arrange
    report = _report(
        [_node("model:m", duration=duration), _node("router:r", duration=100 - duration)]
    )

    # Act
    kinds = _kinds(build_findings(report))

    # Assert
    assert (("duration_concentration", "model:m") in kinds) is expected


def test_duration_statement_distinguishes_overlapping_otlp_spans() -> None:
    # Arrange
    nodes = [_node("model:m", duration=80), _node("router:r", duration=20)]
    plain = _report(nodes)
    otlp = _report(nodes, warnings=[{"code": "otlp_chronological_adjacency"}])

    # Act
    plain_items = build_findings(plain)["items"]
    otlp_items = build_findings(otlp)["items"]

    # Assert
    assert isinstance(plain_items, list) and isinstance(otlp_items, list)
    assert "of summed event duration" in str(plain_items[0]["statement"])
    assert "not wall-clock time" in str(otlp_items[0]["statement"])


def test_concentrations_need_two_categories_and_a_positive_total() -> None:
    assert build_findings(_report([_node("model:m", duration=50)]))["items"] == []
    zero = _report([_node("model:m"), _node("router:r")])
    assert build_findings(zero)["items"] == []


def test_cost_concentration_requires_present_cost_and_states_missing_values() -> None:
    # Arrange
    report = _report(
        [
            _node("model:m", events=10, cost=0.9, cost_count=4),
            _node("tool:t", events=10, cost=0.1, cost_count=2),
        ]
    )

    # Act
    items = build_findings(report)["items"]

    # Assert
    assert isinstance(items, list)
    assert [(item["kind"], item["label"]) for item in items] == [("cost_concentration", "model:m")]
    assert "6 of its event(s) had no cost value" in str(items[0]["statement"])


@pytest.mark.parametrize(("retry_traces", "expected"), [(3, True), (2, False)])
def test_retry_prevalence_threshold(retry_traces: int, expected: bool) -> None:
    # Arrange: 3 of 30 traces is exactly 10%.
    node = _node("tool:x")
    retry = {"node_id": node["id"], "trace_count": retry_traces}
    report = _report([node], traces=30, retries=[retry])

    # Act
    kinds = _kinds(build_findings(report, min_support=2))

    # Assert
    assert (("retry_prevalence", "tool:x") in kinds) is expected


def test_retry_for_unknown_node_is_ignored() -> None:
    report = _report([], traces=10, retries=[{"node_id": "missing", "trace_count": 9}])
    assert build_findings(report)["items"] == []


def test_ranking_uses_kind_effect_support_then_id_and_caps_items() -> None:
    # Arrange: twelve equal error hotspots plus one stronger one.
    nodes = [_node(f"tool:t{index:02d}", events=10, errors=5) for index in range(12)]
    nodes.append(_node("tool:strong", events=10, errors=9))
    nodes.append(_node("tool:wide", events=20, errors=10))

    # Act
    items = build_findings(_report(nodes))["items"]

    # Assert
    assert isinstance(items, list)
    assert len(items) == 10
    labels = [item["label"] for item in items]
    assert labels[0] == "tool:strong"
    assert labels[1] == "tool:wide"
    remaining = [node for node in nodes if node["label"].startswith("tool:t")]
    expected_ids = sorted(str(node["id"]) for node in remaining)[:8]
    assert [item["node_id"] for item in items[2:]] == expected_ids


def test_findings_tolerate_malformed_payload_fields() -> None:
    # Arrange
    report = {
        "nodes": [{"id": "x", "label": "a:b", "event_count": True, "metrics": []}, "bad"],
        "outcomes": [],
        "retries": "bad",
        "warnings": None,
        "totals": {"traces": 2.0},
    }

    # Act / Assert
    assert build_findings(report)["items"] == []
