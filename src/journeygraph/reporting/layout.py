"""Deterministic layered (left-to-right) layout for the aggregate journey graph.

The layout is presentation only: it is computed from an already-built analysis payload and is
never serialized into ``analysis.json``.  It uses no randomness and orders nodes with exact
``Fraction`` barycenters, so the same payload yields byte-identical coordinates everywhere.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

MAX_NODES = 60
SWEEPS = 8
NODE_WIDTH = 184
NODE_HEIGHT = 56
LAYER_GAP = 250
SLOT_GAP = 92
MARGIN_X = 48
TOP = 132
BOTTOM = 96


@dataclass(frozen=True, slots=True)
class PlacedNode:
    """A visible aggregate node with its layer, slot, and center coordinates."""

    node_id: str
    layer: int
    slot: int
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class PlacedEdge:
    """A visible transition and how it is drawn: ``forward``, ``return``, or ``self``.

    ``waypoints`` holds the centers of virtual slots a forward edge passes through when it
    spans more than one layer, so it is routed around intermediate categories.
    """

    source: str
    target: str
    kind: str
    waypoints: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class Layout:
    """Complete deterministic layout of the visible part of a graph."""

    nodes: tuple[PlacedNode, ...]
    edges: tuple[PlacedEdge, ...]
    width: int
    height: int
    hidden_count: int

    def position(self, node_id: str) -> PlacedNode:
        """Return the placed node for an ID."""

        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _visible_nodes(nodes: Sequence[Mapping[str, object]]) -> tuple[list[str], int]:
    ranked = sorted(
        {str(node.get("id", "")): node for node in nodes}.items(),
        key=lambda item: (-_int(item[1].get("trace_count")), item[0]),
    )
    visible = sorted(node_id for node_id, _ in ranked[:MAX_NODES])
    return visible, max(0, len(ranked) - MAX_NODES)


def _return_edges(
    visible: Sequence[str],
    adjacency: Mapping[str, Sequence[str]],
    entries: Sequence[Mapping[str, object]],
) -> set[tuple[str, str]]:
    """Mark DFS back edges, starting from the most frequent entries."""

    visible_set = set(visible)
    entry_counts = {
        str(entry.get("node_id", "")): _int(entry.get("count"))
        for entry in entries
        if str(entry.get("node_id", "")) in visible_set
    }
    starts = sorted(entry_counts, key=lambda node_id: (-entry_counts[node_id], node_id))
    starts.extend(node_id for node_id in visible if node_id not in entry_counts)

    state: dict[str, int] = {}  # 1 = on the DFS stack, 2 = finished
    returns: set[tuple[str, str]] = set()
    for start in starts:
        if start in state:
            continue
        state[start] = 1
        stack: list[tuple[str, int]] = [(start, 0)]
        while stack:
            node_id, index = stack[-1]
            neighbors = adjacency.get(node_id, ())
            if index >= len(neighbors):
                state[node_id] = 2
                stack.pop()
                continue
            stack[-1] = (node_id, index + 1)
            target = neighbors[index]
            if state.get(target) == 1:
                returns.add((node_id, target))
            elif target not in state:
                state[target] = 1
                stack.append((target, 0))
    return returns


def _layers(visible: Sequence[str], forward: Sequence[tuple[str, str]]) -> dict[str, int]:
    """Longest-path layering over the acyclic forward edges (Kahn order by node ID)."""

    successors: dict[str, list[str]] = defaultdict(list)
    indegree = dict.fromkeys(visible, 0)
    for source, target in forward:
        successors[source].append(target)
        indegree[target] += 1
    layer = dict.fromkeys(visible, 0)
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    while ready:
        node_id = ready.pop(0)
        for target in sorted(successors[node_id]):
            layer[target] = max(layer[target], layer[node_id] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    return layer


def _order(
    layer: Mapping[str, int],
    forward: Sequence[tuple[str, str]],
    trace_counts: Mapping[str, int],
) -> list[list[str]]:
    """Order each layer with alternating exact barycenter sweeps."""

    layer_count = max(layer.values(), default=-1) + 1
    layers: list[list[str]] = [[] for _ in range(layer_count)]
    for node_id in sorted(layer, key=lambda item: (-trace_counts.get(item, 0), item)):
        layers[layer[node_id]].append(node_id)

    predecessors: dict[str, list[str]] = defaultdict(list)
    successors: dict[str, list[str]] = defaultdict(list)
    for source, target in forward:
        predecessors[target].append(source)
        successors[source].append(target)

    for sweep in range(SWEEPS):
        downward = sweep % 2 == 0
        neighbors = predecessors if downward else successors
        indices = range(1, layer_count) if downward else range(layer_count - 2, -1, -1)
        for index in indices:
            position = {node_id: slot for row in layers for slot, node_id in enumerate(row)}

            def barycenter(
                item: tuple[int, str],
                position: Mapping[str, int] = position,
                neighbors: Mapping[str, Sequence[str]] = neighbors,
            ) -> tuple[Fraction, int]:
                slot, node_id = item
                linked = neighbors.get(node_id, ())
                if not linked:
                    return Fraction(slot), slot
                return Fraction(sum(position[other] for other in linked), len(linked)), slot

            row = layers[index]
            layers[index] = [node_id for _, node_id in sorted(enumerate(row), key=barycenter)]
    return layers


def _virtual_id(source: str, target: str, layer_index: int) -> str:
    return f"virtual:{source}:{target}:{layer_index}"


def _split_long_edges(
    forward: Sequence[tuple[str, str]], layer: Mapping[str, int]
) -> tuple[list[tuple[str, str]], dict[str, int]]:
    """Replace forward edges spanning several layers by chains through virtual slots."""

    segments: list[tuple[str, str]] = []
    virtual: dict[str, int] = {}
    for source, target in forward:
        previous = source
        for layer_index in range(layer[source] + 1, layer[target]):
            current = _virtual_id(source, target, layer_index)
            virtual[current] = layer_index
            segments.append((previous, current))
            previous = current
        segments.append((previous, target))
    return segments, virtual


def compute_layout(
    nodes: Sequence[Mapping[str, object]],
    transitions: Sequence[Mapping[str, object]],
    entries: Sequence[Mapping[str, object]] = (),
) -> Layout:
    """Return a deterministic layered layout for an analysis payload's graph sections."""

    visible, hidden_count = _visible_nodes(nodes)
    visible_set = set(visible)
    trace_counts = {str(node.get("id", "")): _int(node.get("trace_count")) for node in nodes}
    weights: dict[tuple[str, str], int] = {}
    for edge in transitions:
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if source in visible_set and target in visible_set:
            weights[(source, target)] = weights.get((source, target), 0) + _int(edge.get("weight"))

    adjacency: dict[str, list[str]] = defaultdict(list)
    for source, target in sorted(weights, key=lambda key: (key[0], -weights[key], key[1])):
        if source != target:
            adjacency[source].append(target)
    returns = _return_edges(visible, adjacency, entries)

    edges: list[PlacedEdge] = []
    forward: list[tuple[str, str]] = []
    for source, target in sorted(weights):
        if source == target:
            kind = "self"
        elif (source, target) in returns:
            kind = "return"
        else:
            kind = "forward"
            forward.append((source, target))
        edges.append(PlacedEdge(source, target, kind))

    layer = _layers(visible, forward)
    segments, virtual = _split_long_edges(forward, layer)
    layers = _order(layer | virtual, segments, trace_counts)
    largest = max((len(row) for row in layers), default=1)
    centers: dict[str, tuple[int, int, float, float]] = {}
    for layer_index, row in enumerate(layers):
        offset = Fraction(largest - len(row), 2)
        for slot, node_id in enumerate(row):
            x = MARGIN_X + layer_index * LAYER_GAP + NODE_WIDTH / 2
            y = TOP + float(offset + slot) * SLOT_GAP + NODE_HEIGHT / 2
            centers[node_id] = (layer_index, slot, x, y)
    placed = [PlacedNode(node_id, *centers[node_id]) for node_id in sorted(visible)]
    edges = [
        PlacedEdge(
            edge.source,
            edge.target,
            edge.kind,
            tuple(
                centers[_virtual_id(edge.source, edge.target, index)][2:]
                for index in range(layer[edge.source] + 1, layer[edge.target])
            )
            if edge.kind == "forward"
            else (),
        )
        for edge in edges
    ]

    width = 2 * MARGIN_X + max(len(layers) - 1, 0) * LAYER_GAP + NODE_WIDTH
    height = TOP + largest * SLOT_GAP + BOTTOM
    return Layout(
        nodes=tuple(placed),
        edges=tuple(edges),
        width=max(width, 720),
        height=height,
        hidden_count=hidden_count,
    )
