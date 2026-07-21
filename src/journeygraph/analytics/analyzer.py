"""Pure deterministic analytics over normalized JourneyGraph datasets."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from journeygraph.graph import AggregateGraph, build_graph, stable_node_id, stable_path_id

from ._adapters import (
    DatasetLike,
    EventLike,
    TraceLike,
    issue_payload,
    issue_sort_key,
    json_scalar,
    scalar_identity,
    text,
)
from .metrics import summarize_metric

ANALYSIS_SCHEMA_VERSION = "1.0"
_STANDARD_OUTCOMES = ("success", "failure", "handoff", "dropoff", "unknown")


@dataclass(frozen=True, slots=True)
class _TraceView:
    trace: TraceLike
    events: tuple[EventLike, ...]
    node_ids: tuple[str, ...]
    labels: tuple[str, ...]
    outcome: str
    outcome_source: str
    path_id: str


def _rate(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else round(numerator / denominator, 12)


def _ordered_outcomes(counter: Mapping[str, int]) -> tuple[str, ...]:
    extras = sorted(set(counter) - set(_STANDARD_OUTCOMES))
    return (*_STANDARD_OUTCOMES, *extras)


def _outcome_counts(counter: Mapping[str, int]) -> dict[str, int]:
    return {outcome: counter.get(outcome, 0) for outcome in _ordered_outcomes(counter)}


def _outcome_rates(counter: Mapping[str, int], denominator: int) -> dict[str, float]:
    return {
        outcome: _rate(counter.get(outcome, 0), denominator)
        for outcome in _ordered_outcomes(counter)
    }


def _outcome_payload(counter: Mapping[str, int], denominator: int) -> dict[str, object]:
    return {
        "counts": _outcome_counts(counter),
        "rates": _outcome_rates(counter, denominator),
    }


def _trace_views(dataset: DatasetLike) -> tuple[_TraceView, ...]:
    views: list[_TraceView] = []
    for trace in dataset.traces:
        events = tuple(trace.events)
        node_ids = tuple(stable_node_id(event.operation_type, event.component) for event in events)
        labels = tuple(f"{text(event.operation_type)}:{text(event.component)}" for event in events)
        views.append(
            _TraceView(
                trace=trace,
                events=events,
                node_ids=node_ids,
                labels=labels,
                outcome=text(trace.outcome),
                outcome_source=text(trace.outcome_source),
                path_id=stable_path_id(node_ids),
            )
        )
    return tuple(views)


def _point_payload(counts: Mapping[str, int], labels: Mapping[str, str]) -> list[dict[str, object]]:
    return [
        {"node_id": node_id, "label": labels[node_id], "count": counts[node_id]}
        for node_id in sorted(counts)
    ]


def _paths(views: Sequence[_TraceView]) -> list[dict[str, object]]:
    grouped: dict[str, list[_TraceView]] = defaultdict(list)
    for view in views:
        grouped[view.path_id].append(view)

    result: list[dict[str, object]] = []
    for path_id in sorted(grouped):
        path_views = grouped[path_id]
        first = path_views[0]
        outcomes = Counter(view.outcome for view in path_views)
        success_count = outcomes.get("success", 0)
        result.append(
            {
                "path_id": path_id,
                "node_ids": list(first.node_ids),
                "labels": list(first.labels),
                "count": len(path_views),
                "rate": _rate(len(path_views), len(views)),
                "outcomes": _outcome_counts(outcomes),
                "outcome_rates": _outcome_rates(outcomes, len(path_views)),
                "success_count": success_count,
                "non_success_count": len(path_views) - success_count,
                "success_rate": _rate(success_count, len(path_views)),
            }
        )
    return result


def _retries(views: Sequence[_TraceView]) -> list[dict[str, object]]:
    occurrences: Counter[str] = Counter()
    traces: dict[str, set[str]] = defaultdict(set)
    labels: dict[str, str] = {}
    for view in views:
        labels.update(zip(view.node_ids, view.labels, strict=True))
        seen: set[str] = set()
        for previous, current in pairwise(view.node_ids):
            if previous == current:
                occurrences[current] += 1
                seen.add(current)
        for node_id in seen:
            traces[node_id].add(view.trace.trace_id)
    return [
        {
            "node_id": node_id,
            "label": labels[node_id],
            "node_ids": [node_id],
            "labels": [labels[node_id]],
            "count": occurrences[node_id],
            "trace_count": len(traces[node_id]),
        }
        for node_id in sorted(occurrences)
    ]


def _sequence_digest(namespace: str, sequence: Iterable[str]) -> str:
    encoded = json.dumps([namespace, *sequence], ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _loops(views: Sequence[_TraceView]) -> list[dict[str, object]]:
    """Count minimal non-adjacent returns to an exact event category.

    The most recent earlier visit starts the exact loop sequence.  An adjacent repeat is a
    retry and is intentionally excluded from loops, keeping the two measures distinct.
    """

    occurrences: Counter[tuple[str, ...]] = Counter()
    traces: dict[tuple[str, ...], set[str]] = defaultdict(set)
    labels: dict[str, str] = {}
    for view in views:
        labels.update(zip(view.node_ids, view.labels, strict=True))
        last_index: dict[str, int] = {}
        for index, node_id in enumerate(view.node_ids):
            previous_index = last_index.get(node_id)
            if previous_index is not None and index - previous_index > 1:
                sequence = tuple(view.node_ids[previous_index : index + 1])
                occurrences[sequence] += 1
                traces[sequence].add(view.trace.trace_id)
            last_index[node_id] = index

    payloads = [
        {
            "loop_id": _sequence_digest("journeygraph.loop/v1", sequence),
            "node_ids": list(sequence),
            "labels": [labels[node_id] for node_id in sequence],
            "count": occurrences[sequence],
            "trace_count": len(traces[sequence]),
        }
        for sequence in occurrences
    ]
    return sorted(payloads, key=lambda payload: str(payload["loop_id"]))


def _failure_points(
    views: Sequence[_TraceView], labels: Mapping[str, str]
) -> list[dict[str, object]]:
    occurrences: Counter[str] = Counter()
    error_events: Counter[str] = Counter()
    terminal_failures: Counter[str] = Counter()
    traces: dict[str, set[str]] = defaultdict(set)

    for view in views:
        for node_id, event in zip(view.node_ids, view.events, strict=True):
            if text(event.status) == "error":
                occurrences[node_id] += 1
                error_events[node_id] += 1
                traces[node_id].add(view.trace.trace_id)

        if view.outcome == "failure" and view.node_ids:
            terminal_node = view.node_ids[-1]
            terminal_failures[terminal_node] += 1
            traces[terminal_node].add(view.trace.trace_id)
            if text(view.events[-1].status) != "error":
                occurrences[terminal_node] += 1

    node_ids = sorted(set(occurrences) | set(terminal_failures))
    return [
        {
            "node_id": node_id,
            "label": labels[node_id],
            "count": occurrences[node_id],
            "trace_count": len(traces[node_id]),
            "error_event_count": error_events[node_id],
            "terminal_failure_count": terminal_failures[node_id],
        }
        for node_id in node_ids
    ]


def _dropoff_points(
    views: Sequence[_TraceView], labels: Mapping[str, str]
) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    source_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for view in views:
        if view.outcome == "dropoff" and view.node_ids:
            terminal_node = view.node_ids[-1]
            counts[terminal_node] += 1
            source_counts[terminal_node][view.outcome_source] += 1

    return [
        {
            "node_id": node_id,
            "label": labels[node_id],
            "count": counts[node_id],
            "explicit_count": source_counts[node_id].get("explicit", 0),
            "inferred_count": counts[node_id] - source_counts[node_id].get("explicit", 0),
            "outcome_sources": [
                {"source": source, "count": count}
                for source, count in sorted(source_counts[node_id].items())
            ],
        }
        for node_id in sorted(counts)
    ]


def _path_comparison(views: Sequence[_TraceView]) -> list[dict[str, object]]:
    successful = [view for view in views if view.outcome == "success"]
    non_successful = [view for view in views if view.outcome != "success"]
    non_success_outcomes = Counter(view.outcome for view in non_successful)
    return [
        {
            "group": "success",
            "trace_count": len(successful),
            "path_count": len({view.path_id for view in successful}),
        },
        {
            "group": "non_success",
            "trace_count": len(non_successful),
            "path_count": len({view.path_id for view in non_successful}),
            "outcomes": _outcome_counts(non_success_outcomes),
            "outcome_rates": _outcome_rates(non_success_outcomes, len(non_successful)),
        },
    ]


def _metrics(events: Sequence[EventLike]) -> dict[str, object]:
    total_tokens = [
        None
        if event.input_tokens is None and event.output_tokens is None
        else (event.input_tokens or 0) + (event.output_tokens or 0)
        for event in events
    ]
    return {
        "scope": "events",
        "duration_ms": summarize_metric(event.duration_ms for event in events),
        "input_tokens": summarize_metric((event.input_tokens for event in events), integral=True),
        "output_tokens": summarize_metric((event.output_tokens for event in events), integral=True),
        "total_tokens": summarize_metric(total_tokens, integral=True),
        "cost_usd": summarize_metric(event.cost_usd for event in events),
    }


def _cohort_value(view: _TraceView, cohort_key: str) -> tuple[object, bool, bool]:
    values: list[object] = []
    identities: set[str] = set()
    for event in view.events:
        if cohort_key in event.metadata:
            value = event.metadata[cohort_key]
            identity = scalar_identity(value)
            if identity not in identities:
                identities.add(identity)
                values.append(value)
    if not values:
        return None, True, False
    return values[0], False, len(values) > 1


def _cohorts(views: Sequence[_TraceView], cohort_key: str | None) -> dict[str, object]:
    if cohort_key is None:
        return {
            "key": None,
            "missing_trace_count": len(views),
            "conflicting_trace_count": 0,
            "items": [],
        }

    grouped: dict[str, list[_TraceView]] = defaultdict(list)
    values: dict[str, object] = {}
    missing_count = 0
    conflicting_count = 0
    for view in views:
        value, missing, conflicting = _cohort_value(view, cohort_key)
        identity = scalar_identity(value)
        values[identity] = value
        grouped[identity].append(view)
        missing_count += int(missing)
        conflicting_count += int(conflicting)

    items: list[dict[str, object]] = []
    for identity in sorted(grouped):
        cohort_views = grouped[identity]
        cohort_outcomes = Counter(view.outcome for view in cohort_views)
        events = tuple(event for view in cohort_views for event in view.events)
        scalar = json_scalar(values[identity])
        cohort_id = _sequence_digest("journeygraph.cohort/v1", (cohort_key, identity))
        items.append(
            {
                "cohort_id": cohort_id,
                "key": cohort_key,
                "value": scalar,
                "trace_count": len(cohort_views),
                "event_count": len(events),
                "path_count": len({view.path_id for view in cohort_views}),
                "outcomes": _outcome_counts(cohort_outcomes),
                "outcome_rates": _outcome_rates(cohort_outcomes, len(cohort_views)),
                "metrics": _metrics(events),
            }
        )
    items.sort(key=lambda item: str(item["cohort_id"]))
    return {
        "key": cohort_key,
        "missing_trace_count": missing_count,
        "conflicting_trace_count": conflicting_count,
        "items": items,
    }


def _warnings(dataset: DatasetLike) -> list[dict[str, object]]:
    payloads = [issue_payload(issue) for issue in dataset.warnings]
    return sorted(payloads, key=issue_sort_key)


def analyze_dataset(
    dataset: DatasetLike,
    cohort_key: str | None = "cohort",
    tool_version: str = "0.1.0",
) -> dict[str, object]:
    """Return the complete deterministic ``journeygraph.analysis/v1`` payload.

    The function consumes only an accepted normalized dataset.  It performs no I/O and does
    not mutate the dataset or its metadata.
    """

    graph: AggregateGraph = build_graph(dataset)
    views = _trace_views(dataset)
    labels = {node.node_id: node.label for node in graph.nodes}
    paths = _paths(views)
    outcomes = Counter(view.outcome for view in views)

    entries: Counter[str] = Counter(view.node_ids[0] for view in views if view.node_ids)
    terminals: Counter[str] = Counter(view.node_ids[-1] for view in views if view.node_ids)
    transition_count = sum(edge.weight for edge in graph.edges)
    traced_event_count = sum(len(view.events) for view in views)

    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "tool_version": tool_version,
        "config": {"cohort_key": cohort_key},
        "totals": {
            "input_records": int(getattr(dataset, "input_record_count", traced_event_count)),
            "events": traced_event_count,
            "traces": len(views),
            "nodes": len(graph.nodes),
            "transitions": transition_count,
            "unique_transitions": len(graph.edges),
            "paths": len(paths),
            "warnings": len(dataset.warnings),
        },
        "outcomes": _outcome_payload(outcomes, len(views)),
        "nodes": [node.to_payload() for node in graph.nodes],
        "transitions": [edge.to_payload() for edge in graph.edges],
        "entries": _point_payload(entries, labels),
        "terminals": _point_payload(terminals, labels),
        "paths": paths,
        "retries": _retries(views),
        "loops": _loops(views),
        "failure_points": _failure_points(views, labels),
        "dropoff_points": _dropoff_points(views, labels),
        "path_comparison": _path_comparison(views),
        "cohorts": _cohorts(views, cohort_key),
        "metrics": _metrics(tuple(event for view in views for event in view.events)),
        "warnings": _warnings(dataset),
    }
