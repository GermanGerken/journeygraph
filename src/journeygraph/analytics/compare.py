"""Deterministic comparison of two analysis payloads (``journeygraph.diff``).

The comparison consumes two already-computed analysis payloads, so a stored ``analysis.json``
can be compared as well as a fresh one.  It reports observed differences between two samples;
it never claims that a change caused another.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence

from .findings import DEFAULT_MIN_SUPPORT, wilson_bounds

DIFF_SCHEMA_VERSION = "1.0"
MAX_CHANGES = 15
SUCCESS_RATE_THRESHOLD = 0.05
SHARE_THRESHOLD = 0.10
ERROR_RATE_THRESHOLD = 0.10
RELATIVE_THRESHOLD = 0.20
_PRECISION = 12
_KIND_ORDER = (
    "success_rate_change",
    "category_added",
    "category_removed",
    "category_share_change",
    "category_error_rate_change",
    "variant_share_change",
    "cost_per_trace_change",
    "duration_p95_change",
)

Payload = Mapping[str, object]


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, _PRECISION)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else _round(numerator / denominator)


def _delta(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None:
        return None
    return _round(candidate - baseline)


def _relative(baseline: float | None, candidate: float | None) -> float | None:
    if baseline is None or candidate is None or baseline == 0:
        return None
    return _round((candidate - baseline) / baseline)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _signed_points(value: float) -> str:
    return f"{value * 100:+.0f} percentage points"


def _traces(report: Payload) -> int:
    return _int(_mapping(report.get("totals")).get("traces"))


def _known(counts: Mapping[str, object]) -> tuple[int, int]:
    known = sum(_int(count) for outcome, count in counts.items() if outcome != "unknown")
    return _int(counts.get("success")), known


def newcombe_interval(
    baseline_success: int, baseline_total: int, candidate_success: int, candidate_total: int
) -> dict[str, object] | None:
    """Return the 95% Newcombe hybrid score interval for ``candidate - baseline``."""

    if baseline_total <= 0 or candidate_total <= 0:
        return None
    p1 = baseline_success / baseline_total
    p2 = candidate_success / candidate_total
    low1, high1 = wilson_bounds(baseline_success, baseline_total)
    low2, high2 = wilson_bounds(candidate_success, candidate_total)
    difference = p2 - p1
    return {
        "method": "newcombe",
        "level": 0.95,
        "low": _round(max(-1.0, difference - math.hypot(p2 - low2, high1 - p1))),
        "high": _round(min(1.0, difference + math.hypot(high2 - p2, p1 - low1))),
    }


def _outcomes(baseline: Payload, candidate: Payload) -> dict[str, object]:
    base_counts = _mapping(_mapping(baseline.get("outcomes")).get("counts"))
    cand_counts = _mapping(_mapping(candidate.get("outcomes")).get("counts"))
    base_traces, cand_traces = _traces(baseline), _traces(candidate)
    rates = {}
    for outcome in sorted(set(base_counts) | set(cand_counts)):
        base_rate = _ratio(_int(base_counts.get(outcome)), base_traces)
        cand_rate = _ratio(_int(cand_counts.get(outcome)), cand_traces)
        rates[outcome] = {
            "baseline": base_rate,
            "candidate": cand_rate,
            "delta": _delta(base_rate, cand_rate),
        }
    base_success, base_known = _known(base_counts)
    cand_success, cand_known = _known(cand_counts)
    base_rate = _ratio(base_success, base_known)
    cand_rate = _ratio(cand_success, cand_known)
    return {
        "rates": rates,
        "known_success": {
            "baseline": base_rate,
            "candidate": cand_rate,
            "baseline_known": base_known,
            "candidate_known": cand_known,
            "delta": _delta(base_rate, cand_rate),
            "interval": newcombe_interval(base_success, base_known, cand_success, cand_known),
        },
    }


def _status(baseline: object, candidate: object) -> str:
    if baseline is None:
        return "added"
    if candidate is None:
        return "removed"
    return "common"


def _category_side(node: Mapping[str, object] | None, traces: int) -> dict[str, object] | None:
    if node is None:
        return None
    events = _int(node.get("event_count"))
    success, known = _known(_mapping(_mapping(node.get("trace_outcomes")).get("counts")))
    duration = _mapping(_mapping(node.get("metrics")).get("duration_ms"))
    return {
        "trace_count": _int(node.get("trace_count")),
        "trace_share": _ratio(_int(node.get("trace_count")), traces),
        "event_count": events,
        "error_rate": _ratio(_int(node.get("error_event_count")), events),
        "p95_duration_ms": _number(duration.get("p95")),
        "known_success_rate": _ratio(success, known),
    }


def _categories(baseline: Payload, candidate: Payload) -> list[dict[str, object]]:
    base = {str(node.get("id")): node for node in _items(baseline.get("nodes"))}
    cand = {str(node.get("id")): node for node in _items(candidate.get("nodes"))}
    result: list[dict[str, object]] = []
    for node_id in sorted(set(base) | set(cand)):
        base_side = _category_side(base.get(node_id), _traces(baseline))
        cand_side = _category_side(cand.get(node_id), _traces(candidate))
        label = (cand.get(node_id) or base.get(node_id) or {}).get("label", node_id)
        both = base_side is not None and cand_side is not None
        result.append(
            {
                "node_id": node_id,
                "label": str(label),
                "status": _status(base_side, cand_side),
                "baseline": base_side,
                "candidate": cand_side,
                "trace_share_delta": _delta(
                    _number((base_side or {}).get("trace_share")) if both else None,
                    _number((cand_side or {}).get("trace_share")),
                ),
                "error_rate_delta": _delta(
                    _number((base_side or {}).get("error_rate")) if both else None,
                    _number((cand_side or {}).get("error_rate")),
                ),
            }
        )
    return result


def _shares(
    report: Payload, section: str, key: Callable[[Mapping[str, object]], str]
) -> dict[str, tuple[Mapping[str, object], float | None]]:
    traces = _traces(report)
    return {
        key(item): (item, _ratio(_int(item.get("trace_count")), traces))
        for item in _items(report.get(section))
    }


def _share_rows(
    baseline: Payload,
    candidate: Payload,
    section: str,
    key: Callable[[Mapping[str, object]], str],
    describe: Callable[[Mapping[str, object]], dict[str, object]],
    identity: str,
) -> list[dict[str, object]]:
    base = _shares(baseline, section, key)
    cand = _shares(candidate, section, key)
    rows: list[dict[str, object]] = []
    for item_key in sorted(set(base) | set(cand)):
        base_item, base_share = base.get(item_key, (None, None))
        cand_item, cand_share = cand.get(item_key, (None, None))
        reference = cand_item if cand_item is not None else (base_item or {})
        rows.append(
            {
                identity: item_key,
                **describe(reference),
                "status": _status(base_item, cand_item),
                "baseline_trace_count": _int((base_item or {}).get("trace_count")),
                "candidate_trace_count": _int((cand_item or {}).get("trace_count")),
                "baseline_share": base_share if base_item is not None else 0.0,
                "candidate_share": cand_share if cand_item is not None else 0.0,
                "share_delta": _round((cand_share or 0.0) - (base_share or 0.0)),
            }
        )
    return rows


def _transition_key(item: Mapping[str, object]) -> str:
    return f"{item.get('source', '')}>{item.get('target', '')}"


def _transition_description(item: Mapping[str, object]) -> dict[str, object]:
    return {
        "source": str(item.get("source", "")),
        "target": str(item.get("target", "")),
        "labels": [str(item.get("source_label", "")), str(item.get("target_label", ""))],
    }


def _variant_description(item: Mapping[str, object]) -> dict[str, object]:
    parts: list[str] = []
    for step in _items(item.get("steps")):
        labels = [str(label) for label in step.get("labels", [])]  # type: ignore[attr-defined]
        text = " → ".join(labels)
        if step.get("repeated") is True:
            text = f"({text})+" if len(labels) > 1 else f"{text}+"
        parts.append(text)
    return {"label": " → ".join(parts)}


def _metric_side(report: Payload) -> dict[str, float | int | None]:
    metrics = _mapping(report.get("metrics"))
    traces = _traces(report)
    cost = _mapping(metrics.get("cost_usd"))
    tokens = _mapping(metrics.get("total_tokens"))
    duration = _mapping(metrics.get("duration_ms"))
    cost_present = _int(cost.get("count"))
    token_present = _int(tokens.get("count"))
    return {
        "mean_cost_per_trace": _ratio(_number(cost.get("sum")) or 0.0, traces)
        if cost_present
        else None,
        "mean_total_tokens_per_trace": _ratio(_number(tokens.get("sum")) or 0.0, traces)
        if token_present
        else None,
        "duration_p50_ms": _number(duration.get("p50")),
        "duration_p95_ms": _number(duration.get("p95")),
        "cost_present": cost_present,
        "duration_present": _int(duration.get("count")),
    }


def _metrics(baseline: Payload, candidate: Payload) -> dict[str, object]:
    base, cand = _metric_side(baseline), _metric_side(candidate)
    result: dict[str, object] = {}
    for name in (
        "mean_cost_per_trace",
        "mean_total_tokens_per_trace",
        "duration_p50_ms",
        "duration_p95_ms",
    ):
        base_value, cand_value = _number(base[name]), _number(cand[name])
        result[name] = {
            "baseline": base_value,
            "candidate": cand_value,
            "delta": _delta(base_value, cand_value),
            "relative_delta": _relative(base_value, cand_value),
        }
    result["present_counts"] = {
        "baseline": {"cost": base["cost_present"], "duration": base["duration_present"]},
        "candidate": {"cost": cand["cost_present"], "duration": cand["duration_present"]},
    }
    return result


def _change(
    kind: str, subject: str, label: str, effect: float, statement: str
) -> dict[str, object]:
    return {
        "kind": kind,
        "subject": subject,
        "label": label,
        "effect": _round(abs(effect)),
        "statement": statement,
    }


def _changes(diff: Mapping[str, object], min_support: int) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    success = _mapping(_mapping(diff.get("outcomes")).get("known_success"))
    delta = _number(success.get("delta"))
    if (
        delta is not None
        and abs(delta) >= SUCCESS_RATE_THRESHOLD
        and _int(success.get("baseline_known")) >= min_support
        and _int(success.get("candidate_known")) >= min_support
    ):
        changes.append(
            _change(
                "success_rate_change",
                "outcomes",
                "success among known outcomes",
                delta,
                f"Success among known outcomes moved from "
                f"{_percent(_number(success.get('baseline')))} to "
                f"{_percent(_number(success.get('candidate')))} ({_signed_points(delta)}).",
            )
        )

    for category in _items(diff.get("categories")):
        node_id, label = str(category["node_id"]), str(category["label"])
        status = category["status"]
        base, cand = _mapping(category.get("baseline")), _mapping(category.get("candidate"))
        if status == "added" and _int(cand.get("trace_count")) >= min_support:
            share = _number(cand.get("trace_share")) or 0.0
            changes.append(
                _change(
                    "category_added",
                    node_id,
                    label,
                    share,
                    f"{label} is new: it appears in {_percent(share)} of candidate traces "
                    f"({_int(cand.get('trace_count'))}).",
                )
            )
        elif status == "removed" and _int(base.get("trace_count")) >= min_support:
            share = _number(base.get("trace_share")) or 0.0
            changes.append(
                _change(
                    "category_removed",
                    node_id,
                    label,
                    share,
                    f"{label} no longer appears; it was in {_percent(share)} of baseline traces "
                    f"({_int(base.get('trace_count'))}).",
                )
            )
        elif status == "common":
            share_delta = _number(category.get("trace_share_delta"))
            if (
                share_delta is not None
                and abs(share_delta) >= SHARE_THRESHOLD
                and max(_int(base.get("trace_count")), _int(cand.get("trace_count"))) >= min_support
            ):
                changes.append(
                    _change(
                        "category_share_change",
                        node_id,
                        label,
                        share_delta,
                        f"{label} appears in {_percent(_number(cand.get('trace_share')))} of "
                        f"candidate traces versus {_percent(_number(base.get('trace_share')))} "
                        f"({_signed_points(share_delta)}).",
                    )
                )
            error_delta = _number(category.get("error_rate_delta"))
            if (
                error_delta is not None
                and abs(error_delta) >= ERROR_RATE_THRESHOLD
                and min(_int(base.get("event_count")), _int(cand.get("event_count"))) >= min_support
            ):
                changes.append(
                    _change(
                        "category_error_rate_change",
                        node_id,
                        label,
                        error_delta,
                        f"{label} error-event rate moved from "
                        f"{_percent(_number(base.get('error_rate')))} to "
                        f"{_percent(_number(cand.get('error_rate')))} "
                        f"({_signed_points(error_delta)}).",
                    )
                )

    for variant in _items(diff.get("variants")):
        share_delta = _number(variant.get("share_delta")) or 0.0
        support = max(
            _int(variant.get("baseline_trace_count")), _int(variant.get("candidate_trace_count"))
        )
        if abs(share_delta) >= SHARE_THRESHOLD and support >= min_support:
            label = str(variant.get("label", ""))
            changes.append(
                _change(
                    "variant_share_change",
                    str(variant["variant_id"]),
                    label,
                    share_delta,
                    f"Path variant {label} covers "
                    f"{_percent(_number(variant.get('candidate_share')))} of candidate traces "
                    f"versus {_percent(_number(variant.get('baseline_share')))} "
                    f"({_signed_points(share_delta)}).",
                )
            )

    metrics = _mapping(diff.get("metrics"))
    present = _mapping(metrics.get("present_counts"))
    base_present, cand_present = (
        _mapping(present.get("baseline")),
        _mapping(present.get("candidate")),
    )
    for kind, name, presence, describe in (
        ("cost_per_trace_change", "mean_cost_per_trace", "cost", "Mean supplied cost per trace"),
        ("duration_p95_change", "duration_p95_ms", "duration", "Event p95 duration (ms)"),
    ):
        metric = _mapping(metrics.get(name))
        relative = _number(metric.get("relative_delta"))
        if (
            relative is not None
            and abs(relative) >= RELATIVE_THRESHOLD
            and min(_int(base_present.get(presence)), _int(cand_present.get(presence)))
            >= min_support
        ):
            changes.append(
                _change(
                    kind,
                    name,
                    describe,
                    relative,
                    f"{describe} moved from {metric.get('baseline'):g} to "
                    f"{metric.get('candidate'):g} ({relative:+.0%}).",
                )
            )

    changes.sort(
        key=lambda change: (
            _KIND_ORDER.index(str(change["kind"])),
            -(_number(change["effect"]) or 0.0),
            str(change["subject"]),
        )
    )
    return changes[:MAX_CHANGES]


def compare_analyses(
    baseline: Payload, candidate: Payload, *, min_support: int = DEFAULT_MIN_SUPPORT
) -> dict[str, object]:
    """Return the deterministic ``journeygraph.diff`` payload for two analyses."""

    if isinstance(min_support, bool) or not isinstance(min_support, int) or min_support < 1:
        raise ValueError("min_support must be a positive integer")
    diff: dict[str, object] = {
        "diff_schema_version": DIFF_SCHEMA_VERSION,
        "config": {
            "min_support": min_support,
            "baseline_schema_version": baseline.get("schema_version"),
            "candidate_schema_version": candidate.get("schema_version"),
        },
        "totals": {
            "baseline": {
                "traces": _traces(baseline),
                "events": _int(_mapping(baseline.get("totals")).get("events")),
            },
            "candidate": {
                "traces": _traces(candidate),
                "events": _int(_mapping(candidate.get("totals")).get("events")),
            },
        },
        "outcomes": _outcomes(baseline, candidate),
        "categories": _categories(baseline, candidate),
        "transitions": _share_rows(
            baseline,
            candidate,
            "transitions",
            _transition_key,
            _transition_description,
            "transition_id",
        ),
        "variants": _share_rows(
            baseline,
            candidate,
            "path_variants",
            lambda item: str(item.get("variant_id", "")),
            _variant_description,
            "variant_id",
        ),
        "metrics": _metrics(baseline, candidate),
    }
    diff["changes"] = _changes(diff, min_support)
    return diff
