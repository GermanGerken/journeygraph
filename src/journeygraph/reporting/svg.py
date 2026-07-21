"""Dependency-free deterministic SVG graph renderer."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from html import escape


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _node_label(node: Mapping[str, object]) -> str:
    label = node.get("label")
    if isinstance(label, str):
        return label
    return f"{node.get('operation_type', '')}:{node.get('component', '')}"


def render_svg(report: Mapping[str, object]) -> str:
    """Render the aggregate graph without scripts, links, or external resources."""

    raw_nodes = report.get("nodes", [])
    raw_transitions = report.get("transitions", [])
    nodes = (
        [node for node in raw_nodes if isinstance(node, Mapping)]
        if isinstance(raw_nodes, Sequence)
        else []
    )
    transitions = (
        [edge for edge in raw_transitions if isinstance(edge, Mapping)]
        if isinstance(raw_transitions, Sequence)
        else []
    )
    nodes.sort(key=lambda node: str(node.get("id", "")))
    width = max(900, 180 * min(len(nodes), 8))
    height = max(620, 130 * math.ceil(max(len(nodes), 1) / 8))
    center_x = width / 2
    center_y = height / 2
    radius_x = max(260, width / 2 - 150)
    radius_y = max(180, height / 2 - 120)
    positions: dict[str, tuple[float, float]] = {}
    for index, node in enumerate(nodes):
        angle = (2 * math.pi * index / max(len(nodes), 1)) - math.pi / 2
        positions[str(node.get("id", ""))] = (
            center_x + radius_x * math.cos(angle),
            center_y + radius_y * math.sin(angle),
        )

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        '<title id="title">JourneyGraph aggregate transition graph</title>',
        '<desc id="description">Directed weighted transitions across normalized journey '
        "traces.</desc>",
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
        'orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#68748f"/></marker></defs>',
        '<rect width="100%" height="100%" rx="24" fill="#f7f8fc"/>',
        '<g aria-label="transitions">',
    ]
    for edge in sorted(
        transitions,
        key=lambda item: (str(item.get("source", "")), str(item.get("target", ""))),
    ):
        source_id = str(edge.get("source", ""))
        target_id = str(edge.get("target", ""))
        if source_id not in positions or target_id not in positions:
            continue
        source_x, source_y = positions[source_id]
        target_x, target_y = positions[target_id]
        try:
            weight = max(1, int(edge.get("weight", 1)))
        except (TypeError, ValueError):
            weight = 1
        stroke_width = min(8.0, 1.4 + math.log2(weight + 1))
        edge_title = _text(
            f"{edge.get('source_label', source_id)} → "
            f"{edge.get('target_label', target_id)}: {weight}"
        )
        if source_id == target_id:
            path = (
                f"M {source_x + 58:.1f} {source_y - 12:.1f} "
                f"C {source_x + 120:.1f} {source_y - 90:.1f}, "
                f"{source_x - 120:.1f} {source_y - 90:.1f}, "
                f"{source_x - 58:.1f} {source_y - 12:.1f}"
            )
            parts.append(
                f'<path d="{path}" fill="none" stroke="#68748f" stroke-width="{stroke_width:.1f}" '
                f'marker-end="url(#arrow)"><title>{edge_title}</title></path>'
            )
        else:
            dx = target_x - source_x
            dy = target_y - source_y
            distance = max(math.hypot(dx, dy), 1)
            start_x = source_x + dx / distance * 66
            start_y = source_y + dy / distance * 30
            end_x = target_x - dx / distance * 72
            end_y = target_y - dy / distance * 34
            parts.append(
                f'<line x1="{start_x:.1f}" y1="{start_y:.1f}" x2="{end_x:.1f}" y2="{end_y:.1f}" '
                f'stroke="#68748f" stroke-width="{stroke_width:.1f}" marker-end="url(#arrow)">'
                f"<title>{edge_title}</title></line>"
            )
    parts.append('</g><g aria-label="operation categories">')
    for node in nodes:
        node_id = str(node.get("id", ""))
        if node_id not in positions:
            continue
        x, y = positions[node_id]
        label = _node_label(node)
        visible = label if len(label) <= 30 else f"{label[:29]}…"
        count = node.get("event_count", node.get("count", 0))
        parts.extend(
            [
                f'<g id="node-{_text(node_id)}" transform="translate({x:.1f} {y:.1f})">',
                f"<title>{_text(label)} — {_text(count)} event(s)</title>",
                '<rect x="-70" y="-31" width="140" height="62" rx="15" fill="#ffffff" '
                'stroke="#3256a8" stroke-width="2"/>',
                f'<text x="0" y="-3" text-anchor="middle" font-family="system-ui,sans-serif" '
                f'font-size="12" font-weight="650" fill="#18213a">{_text(visible)}</text>',
                f'<text x="0" y="16" text-anchor="middle" font-family="system-ui,sans-serif" '
                f'font-size="11" fill="#59647d">{_text(count)} event(s)</text>',
                "</g>",
            ]
        )
    parts.append("</g></svg>\n")
    return "".join(parts)
