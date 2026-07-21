"""Unit tests for explainable metric summaries."""

from decimal import Decimal

from journeygraph.analytics import summarize_metric


def test_metric_summary_excludes_missing_values_and_uses_nearest_rank() -> None:
    # Arrange
    values = [Decimal("1.5"), None, Decimal("3.5"), Decimal("2.5")]

    # Act
    summary = summarize_metric(values)

    # Assert
    assert summary == {
        "count": 3,
        "missing_count": 1,
        "sum": 7.5,
        "min": 1.5,
        "max": 3.5,
        "mean": 2.5,
        "p50": 2.5,
        "p95": 3.5,
        "percentile_method": "nearest_rank",
    }


def test_metric_summary_reports_all_missing_observations() -> None:
    # Arrange
    values = [None, None]

    # Act
    summary = summarize_metric(values)

    # Assert
    assert summary == {
        "count": 0,
        "missing_count": 2,
        "sum": 0,
        "min": None,
        "max": None,
        "mean": None,
        "p50": None,
        "p95": None,
        "percentile_method": "nearest_rank",
    }
