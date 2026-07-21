"""Immutable aggregate-graph value objects.

The graph layer deliberately owns no I/O.  These records retain the raw labels needed by
reporters while exposing a JSON-ready representation in a deterministic field order.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One aggregate node for an ``(operation_type, component)`` pair."""

    node_id: str
    operation_type: str
    component: str
    event_count: int
    trace_count: int

    @property
    def label(self) -> str:
        """Return the stable human-readable label used by reports."""

        return f"{self.operation_type}:{self.component}"

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-ready node payload."""

        return {
            "id": self.node_id,
            "label": self.label,
            "operation_type": self.operation_type,
            "component": self.component,
            "event_count": self.event_count,
            "trace_count": self.trace_count,
        }


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """One aggregate directed transition between two graph nodes."""

    source: str
    target: str
    source_label: str
    target_label: str
    weight: int
    trace_count: int

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-ready transition payload."""

        return {
            "source": self.source,
            "target": self.target,
            "source_label": self.source_label,
            "target_label": self.target_label,
            "weight": self.weight,
            "trace_count": self.trace_count,
        }


@dataclass(frozen=True, slots=True)
class AggregateGraph:
    """A deterministically ordered aggregate transition graph."""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]

    def to_payload(self) -> dict[str, list[dict[str, object]]]:
        """Return a JSON-ready graph payload."""

        return {
            "nodes": [node.to_payload() for node in self.nodes],
            "transitions": [edge.to_payload() for edge in self.edges],
        }
