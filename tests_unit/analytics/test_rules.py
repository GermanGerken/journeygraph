"""Unit tests for TOML rules and their evaluation."""

from __future__ import annotations

import pytest

from journeygraph.analytics.rules import (
    RuleResult,
    RulesError,
    evaluate_rules,
    parse_rules,
    summary_markdown,
)


def _report(
    success: int = 8,
    failure: int = 2,
    unknown: int = 0,
    errors: int = 1,
    events: int = 20,
    cost: tuple[int, float] = (10, 0.5),
    p95: float | None = 900,
    labels: tuple[str, ...] = ("a",),
) -> dict[str, object]:
    traces = success + failure + unknown
    return {
        "totals": {"traces": traces},
        "outcomes": {"counts": {"success": success, "failure": failure, "unknown": unknown}},
        "nodes": [
            {"id": label, "label": label, "event_count": events, "error_event_count": errors}
            for label in labels[:1]
        ]
        + [{"id": label, "label": label, "event_count": 0} for label in labels[1:]],
        "metrics": {"cost_usd": {"count": cost[0], "sum": cost[1]}, "duration_ms": {"p95": p95}},
    }


def _by_name(results: tuple[RuleResult, ...]) -> dict[str, RuleResult]:
    return {result.name: result for result in results}


def test_thresholds_pass_and_fail_at_their_limits() -> None:
    # Arrange: success 0.8, failure 0.2, unknown 0, error rate 0.05, cost/trace 0.05, p95 900.
    rules = parse_rules(
        """
        [thresholds]
        min_success_rate = 0.8
        max_failure_rate = 0.19
        max_unknown_rate = 0
        max_error_event_rate = 0.05
        max_mean_cost_per_trace = 0.04
        max_p95_duration_ms = 900
        """
    )

    # Act
    results = _by_name(evaluate_rules(rules, _report()))

    # Assert
    assert [name for name, result in results.items() if not result.passed] == [
        "max_failure_rate",
        "max_mean_cost_per_trace",
    ]
    assert results["min_success_rate"].observed == 0.8
    assert results["max_mean_cost_per_trace"].observed == 0.05
    assert list(results) == [
        "min_success_rate",
        "max_failure_rate",
        "max_unknown_rate",
        "max_error_event_rate",
        "max_mean_cost_per_trace",
        "max_p95_duration_ms",
    ]


def test_unavailable_observations_fail_explicitly() -> None:
    rules = parse_rules("[thresholds]\nmax_mean_cost_per_trace = 1\nmax_p95_duration_ms = 1")
    results = evaluate_rules(rules, _report(cost=(0, 0.0), p95=None))
    assert [result.passed for result in results] == [False, False]
    assert all("unavailable" in result.message for result in results)


def test_regressions_compare_against_the_baseline() -> None:
    # Arrange
    rules = parse_rules(
        """
        [regressions]
        max_success_rate_drop = 0.1
        max_error_event_rate_increase = 0.05
        max_mean_cost_per_trace_increase = 0.5
        forbid_new_categories = true
        """
    )
    baseline = _report()
    candidate = _report(success=6, failure=4, errors=3, cost=(10, 0.7), labels=("a", "b"))

    # Act
    results = _by_name(evaluate_rules(rules, candidate, baseline))

    # Assert
    assert results["max_success_rate_drop"].observed == pytest.approx(0.2)
    assert not results["max_success_rate_drop"].passed
    assert results["max_error_event_rate_increase"].observed == pytest.approx(0.1)
    assert results["max_mean_cost_per_trace_increase"].observed == pytest.approx(0.4)
    assert results["max_mean_cost_per_trace_increase"].passed
    assert results["forbid_new_categories"].observed == 1
    assert "b" in results["forbid_new_categories"].message
    assert not results["forbid_new_categories"].passed


def test_regressions_without_values_fail_and_need_a_baseline() -> None:
    rules = parse_rules("[regressions]\nmax_mean_cost_per_trace_increase = 0.1")
    with pytest.raises(RulesError, match="baseline"):
        evaluate_rules(rules, _report())
    result = evaluate_rules(rules, _report(), _report(cost=(0, 0.0)))[0]
    assert not result.passed and result.observed is None
    allowed = parse_rules("[regressions]\nforbid_new_categories = false")
    assert evaluate_rules(allowed, _report(labels=("a", "b")), _report())[0].passed


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[thresholds\n", "invalid TOML"),
        ("[limits]\nx = 1", "unknown table"),
        ("[thresholds]\nmax_cost = 1", "unknown rule"),
        ("[thresholds]\nmin_success_rate = 'high'", "must be a number"),
        ("[thresholds]\nmin_success_rate = true", "must be a number"),
        ("[thresholds]\nmax_p95_duration_ms = -1", "must not be negative"),
        ("[thresholds]\nmax_failure_rate = 1.5", "between 0 and 1"),
        ("[regressions]\nforbid_new_categories = 1", "true or false"),
        ("thresholds = 3", "must be tables"),
        ("", "defines no rule"),
    ],
)
def test_parse_rules_rejects_invalid_documents(text: str, message: str) -> None:
    with pytest.raises(RulesError, match=message):
        parse_rules(text)


def test_summary_markdown_lists_every_rule() -> None:
    results = (
        RuleResult("min_success_rate", True, 0.8, 0.5, "ok"),
        RuleResult("forbid_new_categories", False, 2, True, "new"),
        RuleResult("max_p95_duration_ms", False, None, 100.0, "unavailable"),
    )
    text = summary_markdown(results)
    assert "1 of 3 rule(s) passed." in text
    assert "| `min_success_rate` | pass | 0.8 | 0.5 |" in text
    assert "| `forbid_new_categories` | **fail** | 2 | true |" in text
    assert "| `max_p95_duration_ms` | **fail** | unavailable | 100 |" in text
