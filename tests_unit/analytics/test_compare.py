"""Unit tests for comparing two analysis payloads."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from journeygraph.analytics.compare import MAX_CHANGES, compare_analyses, newcombe_interval


def _node(
    node_id: str, traces: int, events: int, errors: int = 0, success: int = 0, failure: int = 0
) -> dict[str, object]:
    return {
        "id": node_id,
        "label": f"step:{node_id}",
        "trace_count": traces,
        "event_count": events,
        "error_event_count": errors,
        "metrics": {"duration_ms": {"p95": 10}},
        "trace_outcomes": {"counts": {"success": success, "failure": failure, "unknown": 0}},
    }


def _report(
    traces: int,
    success: int,
    failure: int,
    nodes: list[dict[str, object]],
    *,
    unknown: int = 0,
    cost: tuple[int, float] = (0, 0.0),
    p95: float | None = 100,
    variants: list[dict[str, object]] | None = None,
    transitions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "1.2",
        "totals": {"traces": traces, "events": traces * 3},
        "outcomes": {"counts": {"success": success, "failure": failure, "unknown": unknown}},
        "nodes": nodes,
        "transitions": transitions or [],
        "path_variants": variants or [],
        "metrics": {
            "cost_usd": {"count": cost[0], "sum": cost[1]},
            "total_tokens": {"count": 0, "sum": 0},
            "duration_ms": {"count": traces * 3, "p50": 10, "p95": p95},
        },
    }


def _kinds(diff: Mapping[str, object]) -> list[tuple[str, str]]:
    return [(str(item["kind"]), str(item["label"])) for item in diff["changes"]]  # type: ignore[union-attr]


def test_newcombe_interval_matches_published_example() -> None:
    # Newcombe (1998), example (a): 56/70 versus 48/80 gives 0.0524 to 0.3339 for p1 - p2.
    interval = newcombe_interval(56, 70, 48, 80)
    assert interval is not None
    assert interval["low"] == pytest.approx(-0.3339, abs=5e-5)
    assert interval["high"] == pytest.approx(-0.0524, abs=5e-5)
    assert newcombe_interval(0, 0, 1, 2) is None


def test_categories_report_status_shares_and_deltas() -> None:
    # Arrange
    baseline = _report(10, 8, 2, [_node("a", 10, 10, errors=2), _node("gone", 5, 5)])
    candidate = _report(20, 10, 10, [_node("a", 10, 20, errors=10), _node("new", 4, 4)])

    # Act
    diff = compare_analyses(baseline, candidate)

    # Assert
    categories = {item["node_id"]: item for item in diff["categories"]}  # type: ignore[union-attr]
    assert [item["status"] for item in diff["categories"]] == ["common", "removed", "added"]  # type: ignore[union-attr]
    common = categories["a"]
    assert common["trace_share_delta"] == -0.5
    assert common["error_rate_delta"] == pytest.approx(0.3)
    assert categories["new"]["trace_share_delta"] is None
    assert categories["gone"]["candidate"] is None
    success = diff["outcomes"]["known_success"]  # type: ignore[index]
    assert success["baseline"] == 0.8 and success["candidate"] == 0.5
    assert success["delta"] == pytest.approx(-0.3)


def test_changes_follow_thresholds_and_rank_by_kind_then_effect() -> None:
    # Arrange
    baseline = _report(
        10,
        8,
        2,
        [_node("a", 10, 10, errors=1), _node("b", 5, 5), _node("old", 3, 3)],
        cost=(10, 0.1),
        p95=100,
        variants=[
            {"variant_id": "v1", "trace_count": 10, "steps": [{"labels": ["x"], "repeated": True}]}
        ],
    )
    candidate = _report(
        10,
        5,
        5,
        [_node("a", 10, 10, errors=3), _node("b", 7, 7), _node("fresh", 3, 3)],
        cost=(10, 0.13),
        p95=119,
        variants=[
            {
                "variant_id": "v1",
                "trace_count": 9,
                "steps": [{"labels": ["x", "y"], "repeated": True}],
            }
        ],
    )

    # Act
    diff = compare_analyses(baseline, candidate)

    # Assert: cost +30% passes, p95 +19% and variant -10pp within the share threshold.
    assert _kinds(diff) == [
        ("success_rate_change", "success among known outcomes"),
        ("category_added", "step:fresh"),
        ("category_removed", "step:old"),
        ("category_share_change", "step:b"),
        ("category_error_rate_change", "step:a"),
        ("variant_share_change", "(x → y)+"),
        ("cost_per_trace_change", "Mean supplied cost per trace"),
    ]


def test_changes_respect_min_support_and_missing_values() -> None:
    # Arrange
    baseline = _report(2, 2, 0, [_node("a", 2, 2)], cost=(0, 0.0), p95=None)
    candidate = _report(2, 0, 2, [_node("a", 2, 2, errors=2), _node("z", 2, 2)], p95=None)

    # Act
    diff = compare_analyses(baseline, candidate)

    # Assert
    assert diff["changes"] == []
    metrics = diff["metrics"]  # type: ignore[index]
    assert metrics["mean_cost_per_trace"] == {
        "baseline": None,
        "candidate": None,
        "delta": None,
        "relative_delta": None,
    }
    assert _kinds(compare_analyses(baseline, candidate, min_support=1))[0][0] == (
        "success_rate_change"
    )


def test_transitions_and_variants_use_union_with_zero_shares() -> None:
    # Arrange
    edge = {
        "source": "a",
        "target": "b",
        "source_label": "A",
        "target_label": "B",
        "trace_count": 4,
    }
    baseline = _report(4, 4, 0, [], transitions=[edge])
    candidate = _report(4, 4, 0, [])

    # Act
    diff = compare_analyses(baseline, candidate)

    # Assert
    assert diff["transitions"] == [
        {
            "transition_id": "a>b",
            "source": "a",
            "target": "b",
            "labels": ["A", "B"],
            "status": "removed",
            "baseline_trace_count": 4,
            "candidate_trace_count": 0,
            "baseline_share": 1.0,
            "candidate_share": 0.0,
            "share_delta": -1.0,
        }
    ]


def test_changes_are_capped() -> None:
    nodes = [_node(f"n{index:02d}", 5, 5) for index in range(MAX_CHANGES + 5)]
    diff = compare_analyses(_report(10, 5, 5, []), _report(10, 5, 5, nodes))
    assert len(diff["changes"]) == MAX_CHANGES  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", [0, True])
def test_min_support_must_be_positive(invalid: object) -> None:
    with pytest.raises(ValueError):
        compare_analyses({}, {}, min_support=invalid)  # type: ignore[arg-type]
