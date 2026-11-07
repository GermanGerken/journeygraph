"""Dependency-free deterministic SVG graph renderer."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from html import escape

from journeygraph.reporting.layout import NODE_HEIGHT, NODE_WIDTH, PlacedNode, compute_layout

_FONT = 'font-family="system-ui,sans-serif"'
_LABEL_LIMIT = 26

# (upper bound exclusive, fill, stroke, legend text) for the error-event rate of a node.
_NODE_BUCKETS = (
    (0.0, "#ffffff", "#7b8599", "no error events"),
    (0.1, "#fff6e3", "#b7791f", "under 10% error events"),
    (0.3, "#fde7d6", "#c4561a", "10% to 30% error events"),
    (math.inf, "#fbdcdc", "#b42318", "30% or more error events"),
)
# (lower bound inclusive, stroke, marker id, legend text) for success among known outcomes.
_EDGE_BUCKETS = (
    (0.8, "#2f7d4a", "arrow-high", "80% or more success"),
    (0.5, "#b7791f", "arrow-mid", "50% to 80% success"),
    (0.0, "#b42318", "arrow-low", "under 50% success"),
)
_EDGE_UNKNOWN = ("#8a93a6", "arrow-unknown", "no known outcome")


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _node_label(node: Mapping[str, object]) -> str:
    label = node.get("label")
    if isinstance(label, str):
        return label
    return f"{node.get('operation_type', '')}:{node.get('component', '')}"


def _percent(value: float) -> str:
    return f"{value:.0%}"


def _known_success(item: Mapping[str, object]) -> tuple[int, int]:
    outcomes = item.get("trace_outcomes")
    counts = outcomes.get("counts") if isinstance(outcomes, Mapping) else None
    if not isinstance(counts, Mapping):
        return 0, 0
    known = sum(_int(count) for outcome, count in counts.items() if outcome != "unknown")
    return _int(counts.get("success")), known


def _node_style(node: Mapping[str, object]) -> tuple[str, str, float]:
    events = _int(node.get("event_count"))
    errors = _int(node.get("error_event_count"))
    rate = errors / events if events else 0.0
    if errors == 0:
        _, fill, stroke, _ = _NODE_BUCKETS[0]
        return fill, stroke, rate
    for bound, fill, stroke, _ in _NODE_BUCKETS[1:]:
        if rate < bound:
            return fill, stroke, rate
    raise AssertionError("unreachable: the last node bucket is unbounded")  # pragma: no cover


def _edge_style(edge: Mapping[str, object]) -> tuple[str, str, str]:
    success, known = _known_success(edge)
    if known == 0:
        stroke, marker, _ = _EDGE_UNKNOWN
        return stroke, marker, "no known outcome"
    rate = success / known
    description = f"success {success} of {known} known outcome(s) ({_percent(rate)})"
    for bound, stroke, marker, _ in _EDGE_BUCKETS:
        if rate >= bound:
            return stroke, marker, description
    raise AssertionError("unreachable: the last edge bucket starts at zero")  # pragma: no cover


def _markers() -> str:
    markers = [(stroke, marker) for _, stroke, marker, _ in _EDGE_BUCKETS]
    markers.append(_EDGE_UNKNOWN[:2])
    return "".join(
        f'<marker id="{marker}" markerWidth="10" markerHeight="10" refX="9" refY="5" '
        f'orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L10,5 L0,10 Z" '
        f'fill="{stroke}"/></marker>'
        for stroke, marker in markers
    )


def _legend(hidden_count: int) -> str:
    parts = ['<g aria-label="legend">']
    parts.append(
        f'<text x="48" y="34" {_FONT} font-size="12" font-weight="650" fill="#18213a">'
        "Categories: error-event rate</text>"
    )
    for index, (_, fill, stroke, label) in enumerate(_NODE_BUCKETS):
        x = 48 + index * 172
        parts.append(
            f'<rect x="{x}" y="44" width="18" height="14" rx="4" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="2"/>'
            f'<text x="{x + 24}" y="56" {_FONT} font-size="11" fill="#3a4560">{_text(label)}</text>'
        )
    parts.append(
        f'<text x="48" y="82" {_FONT} font-size="12" font-weight="650" fill="#18213a">'
        "Transitions: success among traces with a known outcome</text>"
    )
    edge_legend = [(stroke, label) for _, stroke, _, label in _EDGE_BUCKETS]
    edge_legend.append((_EDGE_UNKNOWN[0], _EDGE_UNKNOWN[2]))
    for index, (stroke, label) in enumerate(edge_legend):
        x = 48 + index * 172
        parts.append(
            f'<line x1="{x}" y1="98" x2="{x + 18}" y2="98" stroke="{stroke}" stroke-width="3"/>'
            f'<text x="{x + 24}" y="102" {_FONT} font-size="11" fill="#3a4560">'
            f"{_text(label)}</text>"
        )
    note = "Dashed arcs return to an earlier category. Chronological adjacency only."
    if hidden_count:
        note += f" {hidden_count} less frequent categories hidden; see analysis.json."
    parts.append(f'<text x="48" y="122" {_FONT} font-size="11" fill="#59647d">{_text(note)}</text>')
    parts.append("</g>")
    return "".join(parts)


def _edge_path(
    source: PlacedNode,
    target: PlacedNode,
    kind: str,
    bottom: float,
    waypoints: Sequence[tuple[float, float]] = (),
) -> str:
    half_width = NODE_WIDTH / 2
    half_height = NODE_HEIGHT / 2
    if kind == "self":
        x, y = source.x, source.y - half_height
        return (
            f"M {x + 24:.1f} {y:.1f} C {x + 48:.1f} {y - 44:.1f}, "
            f"{x - 48:.1f} {y - 44:.1f}, {x - 24:.1f} {y:.1f}"
        )
    if kind == "return":
        start_x, start_y = source.x, source.y + half_height
        end_x, end_y = target.x, target.y + half_height
        depth = bottom - 24 - abs(source.layer - target.layer) * 3
        return (
            f"M {start_x:.1f} {start_y:.1f} C {start_x:.1f} {depth:.1f}, "
            f"{end_x:.1f} {depth:.1f}, {end_x:.1f} {end_y + 6:.1f}"
        )
    points = [(source.x + half_width, source.y)]
    for x, y in waypoints:
        points.extend([(x - half_width, y), (x + half_width, y)])
    points.append((target.x - half_width - 6, target.y))
    commands = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for index in range(1, len(points)):
        (start_x, start_y), (end_x, end_y) = points[index - 1], points[index]
        if index % 2 == 0:  # straight run through a virtual slot
            commands.append(f"L {end_x:.1f} {end_y:.1f}")
            continue
        bend = max((end_x - start_x) / 2, 24)
        commands.append(
            f"C {start_x + bend:.1f} {start_y:.1f}, {end_x - bend:.1f} {end_y:.1f}, "
            f"{end_x:.1f} {end_y:.1f}"
        )
    return " ".join(commands)


def render_svg(report: Mapping[str, object]) -> str:
    """Render the aggregate graph without scripts, links, or external resources."""

    nodes = _items(report.get("nodes"))
    transitions = _items(report.get("transitions"))
    layout = compute_layout(nodes, transitions, _items(report.get("entries")))
    placed = {node.node_id: node for node in layout.nodes}
    node_by_id = {str(node.get("id", "")): node for node in nodes}
    edge_by_key: dict[tuple[str, str], Mapping[str, object]] = {}
    for edge in transitions:
        edge_by_key.setdefault((str(edge.get("source", "")), str(edge.get("target", ""))), edge)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout.width}" '
        f'height="{layout.height}" viewBox="0 0 {layout.width} {layout.height}" role="img" '
        'aria-labelledby="title description">',
        '<title id="title">JourneyGraph aggregate transition graph</title>',
        '<desc id="description">Layered left-to-right graph of chronological transitions '
        "between operation categories, colored by error-event rate and by success among "
        "traces with a known outcome.</desc>",
        f"<defs>{_markers()}</defs>",
        '<rect width="100%" height="100%" rx="24" fill="#f7f8fc"/>',
        _legend(layout.hidden_count),
        '<g aria-label="transitions">',
    ]
    for placed_edge in layout.edges:
        edge = edge_by_key[(placed_edge.source, placed_edge.target)]
        weight = max(1, _int(edge.get("weight")))
        traces = _int(edge.get("trace_count"))
        stroke, marker, description = _edge_style(edge)
        stroke_width = min(8.0, 1.4 + math.log2(weight + 1))
        dash = ' stroke-dasharray="6 5"' if placed_edge.kind == "return" else ""
        title = _text(
            f"{edge.get('source_label', placed_edge.source)} → "
            f"{edge.get('target_label', placed_edge.target)}: {weight} transition(s) across "
            f"{traces} trace(s); {description}"
        )
        path = _edge_path(
            placed[placed_edge.source],
            placed[placed_edge.target],
            placed_edge.kind,
            layout.height,
            placed_edge.waypoints,
        )
        parts.append(
            f'<path d="{path}" fill="none" stroke="{stroke}" stroke-width="{stroke_width:.1f}" '
            f'stroke-opacity="0.85"{dash} marker-end="url(#{marker})"><title>{title}</title></path>'
        )
    parts.append('</g><g aria-label="operation categories">')
    for placed_node in layout.nodes:
        node = node_by_id[placed_node.node_id]
        label = _node_label(node)
        visible = label if len(label) <= _LABEL_LIMIT else f"{label[: _LABEL_LIMIT - 1]}…"
        traces = _int(node.get("trace_count"))
        events = _int(node.get("event_count"))
        errors = _int(node.get("error_event_count"))
        fill, stroke, rate = _node_style(node)
        success, known = _known_success(node)
        outcome_text = (
            f"success {success} of {known} known outcome(s) ({_percent(success / known)})"
            if known
            else "no known outcome"
        )
        title = (
            f"{label} — {events} event(s) in {traces} trace(s); {errors} error event(s) "
            f"({_percent(rate)}); visiting traces: {outcome_text}"
        )
        x, y = placed_node.x, placed_node.y
        parts.extend(
            [
                f'<g id="node-{_text(placed_node.node_id)}" '
                f'transform="translate({x:.1f} {y:.1f})">',
                f"<title>{_text(title)}</title>",
                f'<rect x="{-NODE_WIDTH / 2:.1f}" y="{-NODE_HEIGHT / 2:.1f}" width="{NODE_WIDTH}" '
                f'height="{NODE_HEIGHT}" rx="14" fill="{fill}" stroke="{stroke}" '
                'stroke-width="2"/>',
                f'<text x="0" y="-4" text-anchor="middle" {_FONT} font-size="12" '
                f'font-weight="650" fill="#18213a">{_text(visible)}</text>',
                f'<text x="0" y="14" text-anchor="middle" {_FONT} font-size="11" '
                f'fill="#3a4560">{traces} trace(s) · {_percent(rate)} errors</text>',
                "</g>",
            ]
        )
    parts.append("</g></svg>\n")
    return "".join(parts)
