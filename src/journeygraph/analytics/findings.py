"""Deterministic, association-only ranked observations over an analysis payload.

Every finding is derived from fields already present in the analysis payload, so a reader can
reproduce it from ``analysis.json`` alone.  Findings describe associations; they never claim
causes, predictions, or quality judgements.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence

DEFAULT_MIN_SUPPORT = 3
MAX_FINDINGS = 10
LOW_SUPPORT_THRESHOLD = 10
OUTCOME_DIFFERENCE_THRESHOLD = 0.20
ERROR_RATE_THRESHOLD = 0.20
DURATION_SHARE_THRESHOLD = 0.25
COST_SHARE_THRESHOLD = 0.25
RETRY_PREVALENCE_THRESHOLD = 0.10
WILSON_LEVEL = 0.95
_WILSON_Z = 1.959963984540054
_PRECISION = 12
_OTLP_WARNING = "otlp_chronological_adjacency"

_KIND_PRIORITY = {
    "outcome_association": 0,
    "sequence_association": 1,
    "error_hotspot": 2,
    "duration_concentration": 3,
    "cost_concentration": 4,
    "retry_prevalence": 5,
}

Finding = dict[str, object]


def _round(value: float) -> float:
    return round(value, _PRECISION)


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else _round(numerator / denominator)


def wilson_bounds(successes: int, total: int) -> tuple[float, float]:
    """Return unrounded two-sided 95% Wilson score bounds for a non-empty sample."""

    if total <= 0:
        raise ValueError("total must be positive")
    if not 0 <= successes <= total:
        raise ValueError("successes must be between zero and total")
    proportion = successes / total
    z_squared = _WILSON_Z * _WILSON_Z
    denominator = 1 + z_squared / total
    center = (proportion + z_squared / (2 * total)) / denominator
    margin = (
        _WILSON_Z
        * math.sqrt(proportion * (1 - proportion) / total + z_squared / (4 * total * total))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def wilson_interval(successes: int, total: int) -> dict[str, object] | None:
    """Return the two-sided 95% Wilson score interval, or ``None`` for an empty sample."""

    if total <= 0:
        return None
    low, high = wilson_bounds(successes, total)
    return {"method": "wilson", "level": WILSON_LEVEL, "low": _round(low), "high": _round(high)}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return 0


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def _percent(value: float) -> str:
    return f"{value:.0%}"


def _known(counts: Mapping[str, object]) -> tuple[int, int, int]:
    """Return ``(success, known, unknown)`` trace counts from an outcome-count mapping."""

    unknown = _int(counts.get("unknown", 0))
    total = sum(_int(count) for count in counts.values())
    return _int(counts.get("success", 0)), total - unknown, unknown


def _support_level(*supports: int | None) -> str:
    present = [support for support in supports if support is not None]
    return "low" if any(support < LOW_SUPPORT_THRESHOLD for support in present) else "normal"


def _finding(
    kind: str,
    node: Mapping[str, object],
    *,
    support: int,
    baseline_support: int | None,
    value: float,
    baseline: float | None,
    effect: float,
    interval: dict[str, object] | None,
    statement: str,
    pattern: Mapping[str, object] | None = None,
) -> Finding:
    if pattern is None:
        identity: dict[str, object] = {
            "node_id": str(node.get("id", "")),
            "pattern_id": None,
            "label": str(node.get("label", "")),
            "labels": [str(node.get("label", ""))],
        }
    else:
        labels = [str(label) for label in _labels(pattern)]
        identity = {
            "node_id": None,
            "pattern_id": str(pattern.get("pattern_id", "")),
            "label": " → ".join(labels),
            "labels": labels,
        }
    return {
        "kind": kind,
        **identity,
        "support": support,
        "baseline_support": baseline_support,
        "value": _round(value),
        "baseline": None if baseline is None else _round(baseline),
        "effect": _round(effect),
        "interval": interval,
        "support_level": _support_level(support, baseline_support),
        "statement": statement,
    }


def _labels(item: Mapping[str, object]) -> list[object]:
    labels = item.get("labels")
    if isinstance(labels, Sequence) and not isinstance(labels, (str, bytes)):
        return list(labels)
    return []


def _association(
    kind: str,
    item: Mapping[str, object],
    report: Mapping[str, object],
    min_support: int,
    *,
    subject: str,
    pattern: Mapping[str, object] | None = None,
) -> Finding | None:
    total_success, total_known, _ = _known(_mapping(_mapping(report.get("outcomes")).get("counts")))
    counts = _mapping(_mapping(item.get("trace_outcomes")).get("counts"))
    success, known, unknown = _known(counts)
    other_known = total_known - known
    other_success = total_success - success
    if known < min_support or other_known < min_support:
        return None
    value = _ratio(success, known)
    baseline = _ratio(other_success, other_known)
    difference = _round(abs(value - baseline))
    if difference < OUTCOME_DIFFERENCE_THRESHOLD:
        return None
    statement = (
        f"Traces that include {subject} had a success rate of {_percent(value)} "
        f"(n={known}) versus {_percent(baseline)} (n={other_known}) for traces that do not"
    )
    if unknown:
        noun = "visiting" if pattern is None else "matching"
        statement += f"; {unknown} {noun} trace(s) with an unknown outcome were excluded"
    statement += ". This is an association, not a cause."
    return _finding(
        kind,
        item,
        support=known,
        baseline_support=other_known,
        value=value,
        baseline=baseline,
        effect=difference,
        interval=wilson_interval(success, known),
        statement=statement,
        pattern=pattern,
    )


def _outcome_associations(
    nodes: Sequence[Mapping[str, object]], report: Mapping[str, object], min_support: int
) -> list[Finding]:
    findings: list[Finding] = []
    for node in nodes:
        finding = _association(
            "outcome_association",
            node,
            report,
            min_support,
            subject=str(node.get("label", "")),
        )
        if finding is not None:
            findings.append(finding)
    return findings


def _sequence_associations(
    report: Mapping[str, object], node_findings: Sequence[Finding], min_support: int
) -> list[Finding]:
    """Associate recurring sequences with outcomes, skipping ones a category already explains."""

    explained = {
        (str(finding["node_id"]), _int(finding["support"]), _int(finding["baseline_support"]))
        for finding in node_findings
    }
    findings: list[Finding] = []
    node_ids_by_pattern: dict[str, tuple[str, ...]] = {}
    for pattern in _items(report.get("sequence_patterns")):
        labels = " → ".join(str(label) for label in _labels(pattern))
        finding = _association(
            "sequence_association",
            pattern,
            report,
            min_support,
            subject=f"the sequence {labels}",
            pattern=pattern,
        )
        if finding is None:
            continue
        key_support = (_int(finding["support"]), _int(finding["baseline_support"]))
        node_ids = _labels(_mapping({"labels": pattern.get("node_ids")}))
        if any((str(node_id), *key_support) in explained for node_id in node_ids):
            continue
        node_ids_by_pattern[str(finding["pattern_id"])] = tuple(str(item) for item in node_ids)
        findings.append(finding)

    return _one_per_trace_group(findings, node_ids_by_pattern)


def _contains(longer: tuple[str, ...], shorter: tuple[str, ...]) -> bool:
    width = len(shorter)
    return any(longer[start : start + width] == shorter for start in range(len(longer) - width + 1))


def _one_per_trace_group(
    findings: list[Finding], node_ids_by_pattern: Mapping[str, tuple[str, ...]]
) -> list[Finding]:
    """Report each group of sequences drawn from the same traces once.

    A sequence's matching traces are a subset of those of every window it contains, so a
    containing pair with identical outcome counts matches the same known traces.  Such pairs
    are linked, and each connected group keeps its shortest sequence, then smallest pattern ID.
    Unrelated sequences that merely share counts are all kept.
    """

    findings = sorted(
        findings, key=lambda finding: (len(_labels(finding)), str(finding["pattern_id"]))
    )
    counts = [
        tuple(finding[name] for name in ("support", "baseline_support", "value", "baseline"))
        for finding in findings
    ]
    ids = [node_ids_by_pattern[str(finding["pattern_id"])] for finding in findings]
    group = list(range(len(findings)))

    def root(index: int) -> int:
        while group[index] != index:
            index = group[index]
        return index

    for first in range(len(findings)):
        for second in range(first + 1, len(findings)):
            if counts[first] == counts[second] and _contains(ids[second], ids[first]):
                group[root(second)] = root(first)
    kept: dict[int, Finding] = {}
    for index, finding in enumerate(findings):
        kept.setdefault(root(index), finding)
    return list(kept.values())


def _error_hotspots(
    nodes: Sequence[Mapping[str, object]], report: Mapping[str, object], min_support: int
) -> list[Finding]:
    total_events = sum(_int(node.get("event_count")) for node in nodes)
    total_errors = sum(_int(node.get("error_event_count")) for node in nodes)
    baseline = _ratio(total_errors, total_events)
    findings: list[Finding] = []
    for node in nodes:
        events = _int(node.get("event_count"))
        errors = _int(node.get("error_event_count"))
        if events < min_support:
            continue
        rate = _ratio(errors, events)
        if rate < ERROR_RATE_THRESHOLD:
            continue
        label = str(node.get("label", ""))
        findings.append(
            _finding(
                "error_hotspot",
                node,
                support=events,
                baseline_support=total_events,
                value=rate,
                baseline=baseline,
                effect=rate,
                interval=wilson_interval(errors, events),
                statement=(
                    f"{_percent(rate)} of {label} events had error status ({errors} of {events}) "
                    f"versus {_percent(baseline)} across all events."
                ),
            )
        )
    return findings


def _metric(node: Mapping[str, object], name: str) -> Mapping[str, object]:
    return _mapping(_mapping(node.get("metrics")).get(name))


def _concentrations(
    nodes: Sequence[Mapping[str, object]],
    min_support: int,
    *,
    kind: str,
    metric_name: str,
    threshold: float,
    describe: Callable[[str, float, int, int], str],
) -> list[Finding]:
    if len(nodes) < 2:
        return []
    total = sum(_number(_metric(node, metric_name).get("sum")) for node in nodes)
    if total <= 0:
        return []
    findings: list[Finding] = []
    for node in nodes:
        summary = _metric(node, metric_name)
        present = _int(summary.get("count"))
        missing = _int(summary.get("missing_count"))
        if present < min_support:
            continue
        share = _ratio(_number(summary.get("sum")), total)
        if share < threshold:
            continue
        findings.append(
            _finding(
                kind,
                node,
                support=present,
                baseline_support=None,
                value=share,
                baseline=None,
                effect=share,
                interval=None,
                statement=describe(str(node.get("label", "")), share, present, missing),
            )
        )
    return findings


def _retry_prevalence(
    report: Mapping[str, object],
    nodes_by_id: Mapping[str, Mapping[str, object]],
    min_support: int,
) -> list[Finding]:
    total_traces = _int(_mapping(report.get("totals")).get("traces"))
    findings: list[Finding] = []
    for retry in _items(report.get("retries")):
        node = nodes_by_id.get(str(retry.get("node_id", "")))
        traces = _int(retry.get("trace_count"))
        if node is None or traces < min_support:
            continue
        prevalence = _ratio(traces, total_traces)
        if prevalence < RETRY_PREVALENCE_THRESHOLD:
            continue
        label = str(node.get("label", ""))
        findings.append(
            _finding(
                "retry_prevalence",
                node,
                support=traces,
                baseline_support=total_traces,
                value=prevalence,
                baseline=None,
                effect=prevalence,
                interval=wilson_interval(traces, total_traces),
                statement=(
                    f"{label} was immediately repeated in {_percent(prevalence)} of traces "
                    f"({traces} of {total_traces})."
                ),
            )
        )
    return findings


def _is_otlp(report: Mapping[str, object]) -> bool:
    return any(warning.get("code") == _OTLP_WARNING for warning in _items(report.get("warnings")))


def _rank_key(finding: Finding) -> tuple[int, float, int, str]:
    return (
        _KIND_PRIORITY[str(finding["kind"])],
        -_number(finding["effect"]),
        -_int(finding["support"]),
        str(finding["node_id"] or finding["pattern_id"]),
    )


def build_findings(
    report: Mapping[str, object], *, min_support: int = DEFAULT_MIN_SUPPORT
) -> dict[str, object]:
    """Return at most ten ranked, reproducible observations for an analysis payload."""

    if isinstance(min_support, bool) or not isinstance(min_support, int) or min_support < 1:
        raise ValueError("min_support must be a positive integer")

    nodes = _items(report.get("nodes"))
    nodes_by_id = {str(node.get("id", "")): node for node in nodes}
    otlp = _is_otlp(report)

    def duration_statement(label: str, share: float, present: int, _missing: int) -> str:
        scope = (
            "of summed span durations (spans can overlap, so this is not wall-clock time)"
            if otlp
            else "of summed event duration"
        )
        return f"{label} accounts for {_percent(share)} {scope} across {present} event(s)."

    def cost_statement(label: str, share: float, present: int, missing: int) -> str:
        statement = (
            f"{label} accounts for {_percent(share)} of supplied cost across {present} event(s) "
            "with cost"
        )
        if missing:
            statement += f"; {missing} of its event(s) had no cost value"
        return statement + "."

    node_associations = _outcome_associations(nodes, report, min_support)
    findings = [
        *node_associations,
        *_sequence_associations(report, node_associations, min_support),
        *_error_hotspots(nodes, report, min_support),
        *_concentrations(
            nodes,
            min_support,
            kind="duration_concentration",
            metric_name="duration_ms",
            threshold=DURATION_SHARE_THRESHOLD,
            describe=duration_statement,
        ),
        *_concentrations(
            nodes,
            min_support,
            kind="cost_concentration",
            metric_name="cost_usd",
            threshold=COST_SHARE_THRESHOLD,
            describe=cost_statement,
        ),
        *_retry_prevalence(report, nodes_by_id, min_support),
    ]
    findings.sort(key=_rank_key)
    return {
        "config": {"min_support": min_support, "max_items": MAX_FINDINGS},
        "items": findings[:MAX_FINDINGS],
    }
