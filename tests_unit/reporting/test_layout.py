"""Invariant and regression tests for the deterministic layered graph layout."""

from __future__ import annotations

import random
import xml.etree.ElementTree as ET

from hypothesis import given, settings
from hypothesis import strategies as st

from journeygraph.reporting.layout import (
    MAX_NODES,
    NODE_HEIGHT,
    NODE_WIDTH,
    Layout,
    compute_layout,
)
from journeygraph.reporting.svg import render_svg


def _graph(
    edges: list[tuple[int, int]], node_count: int
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    nodes = [
        {"id": f"n{index:03d}", "label": f"step:n{index}", "trace_count": (index * 7) % 5 + 1}
        for index in range(node_count)
    ]
    weights: dict[tuple[int, int], int] = {}
    for source, target in edges:
        weights[(source, target)] = weights.get((source, target), 0) + 1
    transitions = [
        {"source": f"n{source:03d}", "target": f"n{target:03d}", "weight": weight}
        for (source, target), weight in sorted(weights.items())
    ]
    entries = [{"node_id": "n000", "count": 3}] if node_count else []
    return nodes, transitions, entries


graphs = st.integers(min_value=1, max_value=14).flatmap(
    lambda count: st.tuples(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=count - 1),
                st.integers(min_value=0, max_value=count - 1),
            ),
            max_size=40,
        ),
        st.just(count),
    )
)


def _overlaps(layout: Layout) -> bool:
    boxes = [(node.x, node.y) for node in layout.nodes]
    return any(
        abs(first[0] - second[0]) < NODE_WIDTH and abs(first[1] - second[1]) < NODE_HEIGHT
        for index, first in enumerate(boxes)
        for second in boxes[index + 1 :]
    )


@settings(max_examples=120, deadline=None)
@given(graph=graphs)
def test_layout_invariants_hold_for_arbitrary_graphs(
    graph: tuple[list[tuple[int, int]], int],
) -> None:
    # Arrange
    edges, count = graph
    nodes, transitions, entries = _graph(edges, count)

    # Act
    layout = compute_layout(nodes, transitions, entries)

    # Assert
    placed = {node.node_id: node for node in layout.nodes}
    assert sorted(placed) == sorted(str(node["id"]) for node in nodes)
    assert not _overlaps(layout)
    for edge in layout.edges:
        source, target = placed[edge.source], placed[edge.target]
        if edge.kind == "self":
            assert edge.source == edge.target
        elif edge.kind == "forward":
            assert target.layer > source.layer
            assert target.x > source.x
            assert len(edge.waypoints) == target.layer - source.layer - 1
            assert all(source.x < x < target.x for x, _ in edge.waypoints)
        else:
            assert edge.kind == "return"
    assert all(0 < node.x < layout.width and 0 < node.y < layout.height for node in layout.nodes)


@settings(max_examples=60, deadline=None)
@given(graph=graphs, seed=st.integers(min_value=0, max_value=2**16))
def test_layout_and_svg_ignore_input_order(
    graph: tuple[list[tuple[int, int]], int], seed: int
) -> None:
    # Arrange
    edges, count = graph
    nodes, transitions, entries = _graph(edges, count)
    shuffled_nodes, shuffled_transitions = list(nodes), list(transitions)
    random.Random(seed).shuffle(shuffled_nodes)
    random.Random(seed + 1).shuffle(shuffled_transitions)

    # Act
    original = compute_layout(nodes, transitions, entries)
    permuted = compute_layout(shuffled_nodes, shuffled_transitions, entries)

    # Assert
    assert original == permuted
    assert render_svg(
        {"nodes": nodes, "transitions": transitions, "entries": entries}
    ) == render_svg(
        {"nodes": shuffled_nodes, "transitions": shuffled_transitions, "entries": entries}
    )


def test_linear_flow_reads_left_to_right_and_cycles_become_returns() -> None:
    # Arrange: a -> b -> c -> b, with c also returning to a.
    nodes, transitions, entries = _graph([(0, 1), (1, 2), (2, 1), (2, 0), (1, 1)], 3)

    # Act
    layout = compute_layout(nodes, transitions, entries)

    # Assert
    layers = {node.node_id: node.layer for node in layout.nodes}
    assert layers == {"n000": 0, "n001": 1, "n002": 2}
    kinds = {(edge.source, edge.target): edge.kind for edge in layout.edges}
    assert kinds == {
        ("n000", "n001"): "forward",
        ("n001", "n002"): "forward",
        ("n002", "n001"): "return",
        ("n002", "n000"): "return",
        ("n001", "n001"): "self",
    }


def test_long_edges_are_routed_through_virtual_slots() -> None:
    # Arrange: a -> b -> c -> d plus a shortcut a -> d spanning two intermediate layers.
    nodes, transitions, entries = _graph([(0, 1), (1, 2), (2, 3), (0, 3)], 4)

    # Act
    layout = compute_layout(nodes, transitions, entries)

    # Assert
    shortcut = next(edge for edge in layout.edges if (edge.source, edge.target) == ("n000", "n003"))
    assert len(shortcut.waypoints) == 2
    intermediate = {(node.x, node.y) for node in layout.nodes}
    assert not intermediate & set(shortcut.waypoints)


def test_node_cap_keeps_most_frequent_categories_and_reports_hidden_count() -> None:
    # Arrange
    nodes = [
        {"id": f"n{index:03d}", "label": f"step:{index}", "trace_count": index}
        for index in range(MAX_NODES + 5)
    ]
    transitions = [{"source": "n000", "target": "n064", "weight": 1}]

    # Act
    layout = compute_layout(nodes, transitions)
    svg = render_svg({"nodes": nodes, "transitions": transitions})

    # Assert
    assert layout.hidden_count == 5
    assert len(layout.nodes) == MAX_NODES
    assert {node.node_id for node in layout.nodes} == {f"n{index:03d}" for index in range(5, 65)}
    assert layout.edges == ()
    assert "5 less frequent categories hidden" in svg


def test_empty_graph_renders_a_valid_svg() -> None:
    # Act
    layout = compute_layout([], [])
    root = ET.fromstring(render_svg({}))

    # Assert
    assert layout.nodes == () and layout.edges == ()
    assert root.tag.endswith("svg")


def test_svg_encodes_error_and_success_buckets_with_text_alternatives() -> None:
    # Arrange
    nodes = [
        {
            "id": "a",
            "label": "tool:a",
            "event_count": 10,
            "trace_count": 10,
            "error_event_count": 5,
            "trace_outcomes": {"counts": {"success": 2, "failure": 6, "unknown": 2}},
        },
        {
            "id": "b",
            "label": "model:b",
            "event_count": 10,
            "trace_count": 10,
            "error_event_count": 0,
        },
        {"id": "c", "label": "x:c", "event_count": 20, "trace_count": 2, "error_event_count": 1},
        {"id": "d", "label": "x:d", "event_count": 10, "trace_count": 2, "error_event_count": 2},
    ]
    transitions = [
        {
            "source": "a",
            "target": "b",
            "source_label": "tool:a",
            "target_label": "model:b",
            "weight": 3,
            "trace_count": 3,
            "trace_outcomes": {"counts": {"success": 1, "failure": 2, "unknown": 0}},
        },
        {
            "source": "b",
            "target": "c",
            "weight": 1,
            "trace_count": 1,
            "trace_outcomes": {"counts": {"success": 0, "unknown": 1}},
        },
        {
            "source": "c",
            "target": "d",
            "weight": 1,
            "trace_count": 1,
            "trace_outcomes": {"counts": {"success": 3, "failure": 1}},
        },
        {
            "source": "d",
            "target": "a",
            "weight": 1,
            "trace_count": 1,
            "trace_outcomes": {"counts": {"success": 9, "failure": 1}},
        },
    ]

    # Act
    svg = render_svg({"nodes": nodes, "transitions": transitions})
    root = ET.fromstring(svg)

    # Assert
    titles = [
        "".join(element.itertext()) for element in root.iter() if element.tag.endswith("title")
    ]
    assert any("tool:a — 10 event(s) in 10 trace(s); 5 error event(s) (50%)" in t for t in titles)
    assert any("success 2 of 8 known outcome(s) (25%)" in title for title in titles)
    assert any("success 1 of 3 known outcome(s) (33%)" in title for title in titles)
    assert any("model:b" in title and "no known outcome" in title for title in titles)
    assert 'fill="#fbdcdc"' in svg  # 50% error events
    assert 'fill="#fff6e3"' in svg  # 5% error events
    assert 'fill="#fde7d6"' in svg  # 20% error events
    assert 'marker-end="url(#arrow-low)"' in svg
    assert 'marker-end="url(#arrow-unknown)"' in svg
    assert 'marker-end="url(#arrow-mid)"' in svg
    assert 'marker-end="url(#arrow-high)"' in svg
    assert 'stroke-dasharray="6 5"' in svg


def test_self_loops_on_top_categories_stay_below_the_legend() -> None:
    # Arrange: a single repeating category sits in the top slot.
    nodes, transitions, entries = _graph([(0, 0), (0, 1)], 2)
    svg = ET.fromstring(
        render_svg({"nodes": nodes, "transitions": transitions, "entries": entries})
    )
    namespace = "{http://www.w3.org/2000/svg}"
    legend = next(
        group for group in svg.iter(f"{namespace}g") if group.get("aria-label") == "legend"
    )
    legend_bottom = max(
        float(element.get("y", "0")) + float(element.get("height", "0"))
        for element in legend.iter()
        if element.get("y") is not None
    )

    # Act
    layout = compute_layout(nodes, transitions, entries)

    # Assert: the loop's Bezier control points (a bound on the curve) clear the legend.
    loop_control_y = min(node.y for node in layout.nodes) - NODE_HEIGHT / 2 - 44
    assert loop_control_y > legend_bottom + 4
