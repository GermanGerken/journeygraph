"""Pure deterministic construction of aggregate journey graphs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from itertools import pairwise
from typing import Protocol

from .models import AggregateGraph, GraphEdge, GraphNode


class _EventLike(Protocol):
    @property
    def operation_type(self) -> object: ...

    @property
    def component(self) -> object: ...


class _TraceLike(Protocol):
    @property
    def trace_id(self) -> str: ...

    @property
    def events(self) -> Sequence[_EventLike]: ...


class _DatasetLike(Protocol):
    @property
    def traces(self) -> Sequence[_TraceLike]: ...


def _text(value: object) -> str:
    """Convert strings and string-valued enums to their canonical text."""

    enum_value = getattr(value, "value", value)
    return str(enum_value)


def _digest(namespace: str, parts: Iterable[str]) -> str:
    """Hash a collision-safe, versioned identity representation."""

    encoded = json.dumps([namespace, *parts], ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def stable_node_id(operation_type: object, component: object) -> str:
    """Return the public SHA-256 identity for one aggregate graph node."""

    return _digest("journeygraph.node/v1", (_text(operation_type), _text(component)))


def stable_path_id(node_ids: Iterable[str]) -> str:
    """Return the public SHA-256 identity for an exact ordered node path."""

    return _digest("journeygraph.path/v1", tuple(node_ids))


def build_graph(dataset: _DatasetLike) -> AggregateGraph:
    """Aggregate ordered trace events into deterministic nodes and transitions.

    Each event contributes once to its node.  Each adjacent event pair contributes exactly
    once to an edge's ``weight``; ``trace_count`` counts distinct traces containing that
    node or edge.  The accepted normalized trace order is authoritative.
    """

    node_events: Counter[str] = Counter()
    node_traces: dict[str, set[str]] = defaultdict(set)
    node_labels: dict[str, tuple[str, str]] = {}
    edge_weights: Counter[tuple[str, str]] = Counter()
    edge_traces: dict[tuple[str, str], set[str]] = defaultdict(set)

    for trace in dataset.traces:
        trace_node_ids: list[str] = []
        for event in trace.events:
            operation_type = _text(event.operation_type)
            component = _text(event.component)
            node_id = stable_node_id(operation_type, component)
            node_labels[node_id] = (operation_type, component)
            node_events[node_id] += 1
            node_traces[node_id].add(trace.trace_id)
            trace_node_ids.append(node_id)

        seen_edges: set[tuple[str, str]] = set()
        for source, target in pairwise(trace_node_ids):
            edge = (source, target)
            edge_weights[edge] += 1
            seen_edges.add(edge)
        for edge in seen_edges:
            edge_traces[edge].add(trace.trace_id)

    nodes = tuple(
        GraphNode(
            node_id=node_id,
            operation_type=node_labels[node_id][0],
            component=node_labels[node_id][1],
            event_count=node_events[node_id],
            trace_count=len(node_traces[node_id]),
        )
        for node_id in sorted(node_labels)
    )
    labels_by_id = {node.node_id: node.label for node in nodes}
    edges = tuple(
        GraphEdge(
            source=source,
            target=target,
            source_label=labels_by_id[source],
            target_label=labels_by_id[target],
            weight=edge_weights[(source, target)],
            trace_count=len(edge_traces[(source, target)]),
        )
        for source, target in sorted(edge_weights)
    )
    return AggregateGraph(nodes=nodes, edges=edges)
