"""Unit tests for deterministic aggregate graph construction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from journeygraph.domain import CanonicalEvent, NormalizedDataset, Trace
from journeygraph.graph import build_graph, stable_node_id, stable_path_id


def _event(trace_id: str, step: int, operation_type: str, component: str) -> CanonicalEvent:
    return CanonicalEvent(
        trace_id=trace_id,
        step_id=f"s{step}",
        parent_step_id=None,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=step),
        operation_type=operation_type,
        component=component,
        duration_ms=Decimal("1"),
        status="ok",
        outcome=None,
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
    )


def _dataset(*traces: Trace) -> NormalizedDataset:
    events = tuple(event for trace in traces for event in trace.events)
    return NormalizedDataset(
        events=events,
        traces=traces,
        warnings=(),
        input_format="jsonl",
        input_record_count=len(events),
    )


def test_stable_ids_match_manually_frozen_sha256_oracles() -> None:
    # Arrange
    expected_router_id = "5f2cdce41718737b1357ae7bc3cc60e6809444ab210f04801aeff77cdacc94b5"
    expected_tool_id = "192468d70a352f82fc5f5c31737e0cff599b482486433a5e45dba868f2c57b4b"
    expected_unicode_id = "614dcd742fe1b3ce267aa4c363207bc66e069ad3918b12bab7b328cb16b246ee"
    expected_path_id = "ee533c68a339115e0f9912cd479a04014a2ffd306a738bb9797bb009e5343af2"

    # Act
    router_id = stable_node_id("router", "main")
    tool_id = stable_node_id("tool", "search")
    unicode_id = stable_node_id("tool", "Поиск 🔎")
    path_id = stable_path_id((router_id, tool_id, router_id))

    # Assert
    assert router_id == expected_router_id
    assert tool_id == expected_tool_id
    assert unicode_id == expected_unicode_id
    assert path_id == expected_path_id


def test_build_graph_matches_manual_node_and_transition_counts() -> None:
    # Arrange
    router_id = "5f2cdce41718737b1357ae7bc3cc60e6809444ab210f04801aeff77cdacc94b5"
    tool_id = "192468d70a352f82fc5f5c31737e0cff599b482486433a5e45dba868f2c57b4b"
    trace_one = Trace(
        trace_id="t1",
        events=(
            _event("t1", 1, "router", "main"),
            _event("t1", 2, "tool", "search"),
            _event("t1", 3, "router", "main"),
        ),
        outcome="success",
        outcome_source="explicit",
    )
    trace_two = Trace(
        trace_id="t2",
        events=(
            _event("t2", 1, "router", "main"),
            _event("t2", 2, "tool", "search"),
            _event("t2", 3, "tool", "search"),
        ),
        outcome="dropoff",
        outcome_source="missing",
    )

    # Act
    graph = build_graph(_dataset(trace_one, trace_two))

    # Assert
    nodes = {node.node_id: node for node in graph.nodes}
    assert {
        node_id: (node.label, node.event_count, node.trace_count) for node_id, node in nodes.items()
    } == {
        router_id: ("router:main", 3, 2),
        tool_id: ("tool:search", 3, 2),
    }
    assert {
        (edge.source, edge.target): (edge.weight, edge.trace_count) for edge in graph.edges
    } == {
        (router_id, tool_id): (2, 2),
        (tool_id, router_id): (1, 1),
        (tool_id, tool_id): (1, 1),
    }
    assert sum(edge.weight for edge in graph.edges) == 4
    assert graph.to_payload() == {
        "nodes": [node.to_payload() for node in graph.nodes],
        "transitions": [edge.to_payload() for edge in graph.edges],
    }


def test_build_graph_is_invariant_to_trace_input_order() -> None:
    # Arrange
    trace_one = Trace(
        trace_id="t1",
        events=(_event("t1", 1, "router", "main"),),
        outcome="success",
        outcome_source="explicit",
    )
    trace_two = Trace(
        trace_id="t2",
        events=(
            _event("t2", 1, "router", "main"),
            _event("t2", 2, "tool", "search"),
        ),
        outcome="failure",
        outcome_source="terminal_status",
    )

    # Act
    forward = build_graph(_dataset(trace_one, trace_two))
    reversed_order = build_graph(_dataset(trace_two, trace_one))

    # Assert
    assert forward == reversed_order
    assert [node.node_id for node in forward.nodes] == sorted(
        node.node_id for node in forward.nodes
    )
    assert [(edge.source, edge.target) for edge in forward.edges] == sorted(
        (edge.source, edge.target) for edge in forward.edges
    )
