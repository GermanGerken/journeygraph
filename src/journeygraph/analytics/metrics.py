"""Explainable deterministic metric summaries."""

from __future__ import annotations

import math
from collections.abc import Iterable
from decimal import Decimal

from ._adapters import json_number

Numeric = Decimal | int | float


def _decimal(value: Numeric) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _nearest_rank(values: list[Decimal], percentile: Decimal) -> Decimal:
    """Return a nearest-rank percentile from a non-empty sorted sequence."""

    rank = max(1, math.ceil(float(percentile * len(values))))
    return values[rank - 1]


def summarize_metric(
    values: Iterable[Numeric | None], *, integral: bool = False
) -> dict[str, object]:
    """Summarize present values and explicitly count missing observations.

    Percentiles use the simple one-indexed nearest-rank definition.  Missing values never
    enter sums, means, extrema, or percentiles.
    """

    observations = list(values)
    present = sorted(_decimal(value) for value in observations if value is not None)
    missing_count = len(observations) - len(present)

    if not present:
        return {
            "count": 0,
            "missing_count": missing_count,
            "sum": 0,
            "min": None,
            "max": None,
            "mean": None,
            "p50": None,
            "p95": None,
            "percentile_method": "nearest_rank",
        }

    total = sum(present, Decimal(0))
    mean = total / len(present)

    def number(value: Decimal) -> int | float:
        converted = json_number(value)
        if integral and value == value.to_integral_value():
            return int(value)
        return converted

    return {
        "count": len(present),
        "missing_count": missing_count,
        "sum": number(total),
        "min": number(present[0]),
        "max": number(present[-1]),
        "mean": number(mean),
        "p50": number(_nearest_rank(present, Decimal("0.50"))),
        "p95": number(_nearest_rank(present, Decimal("0.95"))),
        "percentile_method": "nearest_rank",
    }
