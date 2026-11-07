"""Declarative journey-level rules evaluated by ``journeygraph check``.

Rules are read from TOML with the standard library and evaluated only against analysis
payloads (and, for regression rules, a comparison payload), so results are reproducible from
``analysis.json``.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .compare import Payload, compare_analyses

_THRESHOLDS = (
    "min_success_rate",
    "max_failure_rate",
    "max_unknown_rate",
    "max_error_event_rate",
    "max_mean_cost_per_trace",
    "max_p95_duration_ms",
)
_REGRESSIONS = (
    "max_success_rate_drop",
    "max_error_event_rate_increase",
    "max_mean_cost_per_trace_increase",
    "forbid_new_categories",
)


class RulesError(ValueError):
    """A rules document is malformed or inconsistent with the requested check."""


@dataclass(frozen=True, slots=True)
class Rules:
    """Validated thresholds and regression limits."""

    thresholds: Mapping[str, float]
    regressions: Mapping[str, float | bool]

    @property
    def needs_baseline(self) -> bool:
        """Return whether any regression rule is configured."""

        return bool(self.regressions)


@dataclass(frozen=True, slots=True)
class RuleResult:
    """One evaluated rule."""

    name: str
    passed: bool
    observed: float | int | bool | None
    limit: float | bool
    message: str

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-ready representation."""

        return {
            "name": self.name,
            "passed": self.passed,
            "observed": self.observed,
            "limit": self.limit,
            "message": self.message,
        }


def _number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RulesError(f"{name} must be a number")
    if value < 0:
        raise RulesError(f"{name} must not be negative")
    return float(value)


def parse_rules(text: str) -> Rules:
    """Parse and validate a TOML rules document."""

    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise RulesError(f"invalid TOML: {error}") from None
    unknown_tables = sorted(set(document) - {"thresholds", "regressions"})
    if unknown_tables:
        raise RulesError(f"unknown table(s): {', '.join(unknown_tables)}")

    thresholds_raw = document.get("thresholds", {})
    regressions_raw = document.get("regressions", {})
    if not isinstance(thresholds_raw, dict) or not isinstance(regressions_raw, dict):
        raise RulesError("thresholds and regressions must be tables")
    unknown = sorted(set(thresholds_raw) - set(_THRESHOLDS)) + sorted(
        set(regressions_raw) - set(_REGRESSIONS)
    )
    if unknown:
        raise RulesError(f"unknown rule(s): {', '.join(unknown)}")

    thresholds = {name: _number(name, thresholds_raw[name]) for name in thresholds_raw}
    for name in ("min_success_rate", "max_failure_rate", "max_unknown_rate"):
        if name in thresholds and thresholds[name] > 1:
            raise RulesError(f"{name} must be between 0 and 1")
    regressions: dict[str, float | bool] = {}
    for name, value in regressions_raw.items():
        if name == "forbid_new_categories":
            if not isinstance(value, bool):
                raise RulesError("forbid_new_categories must be true or false")
            regressions[name] = value
        else:
            regressions[name] = _number(name, value)
    if not thresholds and not regressions:
        raise RulesError("the rules document defines no rule")
    return Rules(
        thresholds={name: thresholds[name] for name in _THRESHOLDS if name in thresholds},
        regressions={name: regressions[name] for name in _REGRESSIONS if name in regressions},
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _observations(report: Payload) -> dict[str, float | None]:
    counts = _mapping(_mapping(report.get("outcomes")).get("counts"))
    traces = _int(_mapping(report.get("totals")).get("traces"))
    unknown = _int(counts.get("unknown"))
    known = sum(_int(count) for outcome, count in counts.items() if outcome != "unknown")
    nodes = report.get("nodes")
    node_items = nodes if isinstance(nodes, Sequence) and not isinstance(nodes, str) else []
    events = sum(_int(_mapping(node).get("event_count")) for node in node_items)
    errors = sum(_int(_mapping(node).get("error_event_count")) for node in node_items)
    metrics = _mapping(report.get("metrics"))
    cost = _mapping(metrics.get("cost_usd"))
    duration = _mapping(metrics.get("duration_ms"))
    return {
        "success_rate": _int(counts.get("success")) / known if known else None,
        "failure_rate": _int(counts.get("failure")) / known if known else None,
        "unknown_rate": unknown / traces if traces else None,
        "error_event_rate": errors / events if events else None,
        "mean_cost_per_trace": (_float(cost.get("sum")) or 0.0) / traces
        if traces and _int(cost.get("count"))
        else None,
        "p95_duration_ms": _float(duration.get("p95")),
    }


_THRESHOLD_CHECKS: Mapping[str, tuple[str, Callable[[float, float], bool], str]] = {
    "min_success_rate": (
        "success_rate",
        lambda observed, limit: observed >= limit,
        "success among known outcomes",
    ),
    "max_failure_rate": (
        "failure_rate",
        lambda observed, limit: observed <= limit,
        "failure among known outcomes",
    ),
    "max_unknown_rate": (
        "unknown_rate",
        lambda observed, limit: observed <= limit,
        "unknown outcomes among traces",
    ),
    "max_error_event_rate": (
        "error_event_rate",
        lambda observed, limit: observed <= limit,
        "error events among events",
    ),
    "max_mean_cost_per_trace": (
        "mean_cost_per_trace",
        lambda observed, limit: observed <= limit,
        "mean supplied cost per trace",
    ),
    "max_p95_duration_ms": (
        "p95_duration_ms",
        lambda observed, limit: observed <= limit,
        "event p95 duration (ms)",
    ),
}


def _format(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.6g}"


def evaluate_rules(
    rules: Rules, report: Payload, baseline: Payload | None = None
) -> tuple[RuleResult, ...]:
    """Evaluate every configured rule in a fixed order."""

    if rules.needs_baseline and baseline is None:
        raise RulesError("regression rules require --baseline")
    observed = _observations(report)
    results: list[RuleResult] = []
    for name, limit in rules.thresholds.items():
        key, accept, description = _THRESHOLD_CHECKS[name]
        value = observed[key]
        passed = value is not None and accept(value, limit)
        results.append(
            RuleResult(
                name,
                passed,
                None if value is None else round(value, 12),
                limit,
                f"{description} is {_format(value)} (limit {limit:g})",
            )
        )

    if baseline is not None and rules.regressions:
        before = _observations(baseline)
        diff = compare_analyses(baseline, report)
        for name, limit in rules.regressions.items():
            results.append(_regression(name, limit, before, observed, diff))
    return tuple(results)


def _regression(
    name: str,
    limit: float | bool,
    before: Mapping[str, float | None],
    after: Mapping[str, float | None],
    diff: Mapping[str, object],
) -> RuleResult:
    if name == "forbid_new_categories":
        added = sorted(
            str(_mapping(item).get("label"))
            for item in diff.get("categories", [])  # type: ignore[attr-defined]
            if _mapping(item).get("status") == "added"
        )
        passed = not limit or not added
        detail = ", ".join(added) if added else "none"
        return RuleResult(name, passed, len(added), limit, f"new categories: {detail}")

    if isinstance(limit, bool):
        raise RulesError(f"{name} must be a number")
    metric, description, relative = {
        "max_success_rate_drop": ("success_rate", "success among known outcomes dropped by", False),
        "max_error_event_rate_increase": (
            "error_event_rate",
            "error-event rate increased by",
            False,
        ),
        "max_mean_cost_per_trace_increase": (
            "mean_cost_per_trace",
            "mean cost per trace increased by (relative)",
            True,
        ),
    }[name]
    old, new = before[metric], after[metric]
    if old is None or new is None or (relative and old == 0):
        return RuleResult(name, False, None, limit, f"{description} unavailable on one side")
    change = (old - new) if name == "max_success_rate_drop" else (new - old)
    if relative:
        change = change / old
    change = round(change, 12)
    return RuleResult(
        name, change <= limit, change, limit, f"{description} {change:.6g} (limit {limit:g})"
    )


def _cell(value: float | int | bool | None) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, bool):
        return "true" if value else "false"
    return f"{value:.6g}"


def summary_markdown(results: Sequence[RuleResult]) -> str:
    """Render a Markdown table suitable for a CI step summary."""

    failed = sum(1 for result in results if not result.passed)
    lines = [
        "## JourneyGraph check",
        "",
        f"{len(results) - failed} of {len(results)} rule(s) passed.",
        "",
        "| Rule | Result | Observed | Limit |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{result.name}` | {'pass' if result.passed else '**fail**'} | "
        f"{_cell(result.observed)} | {_cell(result.limit)} |"
        for result in results
    )
    return "\n".join(lines) + "\n"
