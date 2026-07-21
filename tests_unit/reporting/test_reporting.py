from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from journeygraph.reporting.html import render_html
from journeygraph.reporting.serialize import serialize_analysis, serialize_embedded_analysis
from journeygraph.reporting.svg import render_svg


def _report(component: str = "Search") -> dict[str, object]:
    node_id = "a" * 64
    return {
        "schema_version": "1.0",
        "tool_version": "0.1.0",
        "config": {"cohort_key": "cohort"},
        "totals": {"events": 1, "traces": 1},
        "outcomes": {"counts": {"success": 1}},
        "nodes": [
            {
                "id": node_id,
                "label": f"tool:{component}",
                "operation_type": "tool",
                "component": component,
                "event_count": 1,
            }
        ],
        "transitions": [
            {
                "source": node_id,
                "target": node_id,
                "source_label": f"tool:{component}",
                "target_label": f"tool:{component}",
                "weight": 2,
                "trace_count": 1,
            }
        ],
        "entries": [],
        "terminals": [],
        "paths": [
            {
                "labels": [f"tool:{component}"],
                "count": 1,
                "success_rate": 1.0,
                "outcomes": {"success": 1},
            }
        ],
        "retries": [],
        "loops": [],
        "failure_points": [],
        "dropoff_points": [],
        "path_comparison": [],
        "cohorts": {
            "items": [
                {
                    "value": "alpha",
                    "trace_count": 1,
                    "outcomes": {"success": 1},
                    "outcome_rates": {"success": 1.0},
                }
            ]
        },
        "metrics": {
            "duration_ms": {
                "count": 1,
                "missing_count": 0,
                "sum": 2,
                "mean": 2,
                "p95": 2,
            }
        },
        "warnings": [],
    }


def test_reports_escape_hostile_text_and_embed_non_executable_json() -> None:
    # Arrange
    hostile = "</text><script id='owned'>alert(1)</script><text onload='x'>&"
    report = _report(hostile)

    # Act
    html = render_html(report)
    svg = render_svg(report)
    parsed_svg = ET.fromstring(svg)

    # Assert
    assert "<script id='owned'>" not in html
    assert "<script id='owned'>" not in svg
    assert "\\u003c/script\\u003e" in html
    assert "application/json" in html
    assert "default-src 'none'" in html
    assert any(hostile in text for text in parsed_svg.itertext())
    assert all(element.tag.rsplit("}", 1)[-1] != "script" for element in parsed_svg.iter())


def test_html_uses_nested_cohort_outcome_rate() -> None:
    # Arrange
    report = _report()

    # Act
    html = render_html(report)

    # Assert
    assert "<td>alpha</td><td>1</td><td>1</td>" in html


def test_html_sorts_frequent_items_before_limits_with_stable_ties() -> None:
    # Arrange
    report = _report()
    low_paths = [
        {
            "path_id": f"path-{index:02d}",
            "labels": [f"low-path-{index:02d}"],
            "count": 1,
            "success_rate": 0.0,
            "outcomes": {"failure": 1},
        }
        for index in reversed(range(21))
    ]
    dominant_path = {
        "path_id": "zzzz-dominant-path",
        "labels": ["dominant-path"],
        "count": 999,
        "success_rate": 1.0,
        "outcomes": {"success": 999},
    }
    low_transitions = [
        {
            "source": f"source-{index:02d}",
            "target": f"target-{index:02d}",
            "source_label": f"low-source-{index:02d}",
            "target_label": f"low-target-{index:02d}",
            "weight": 1,
            "trace_count": 1,
        }
        for index in reversed(range(31))
    ]
    dominant_transition = {
        "source": "zzzz-dominant-source",
        "target": "zzzz-dominant-target",
        "source_label": "dominant-source",
        "target_label": "dominant-target",
        "weight": 999,
        "trace_count": 1,
    }
    report.update(
        {
            "paths": [*low_paths, dominant_path],
            "transitions": [*low_transitions, dominant_transition],
        }
    )

    # Act
    html = render_html(report)

    # Assert
    assert "<td>dominant-path</td><td>999</td>" in html
    assert html.index("<td>dominant-path</td>") < html.index("<td>low-path-00</td>")
    assert "<td>low-path-19</td>" not in html
    assert "<td>low-path-20</td>" not in html
    assert "<td>dominant-source</td><td>dominant-target</td><td>999</td><td>1</td>" in html
    assert html.index("<td>dominant-source</td>") < html.index("<td>low-source-00</td>")
    assert "<td>low-source-29</td><td>low-target-29</td>" not in html
    assert "<td>low-source-30</td><td>low-target-30</td>" not in html


def test_html_reports_terminal_failures_separately_from_error_events() -> None:
    # Arrange
    report = _report()
    report["failure_points"] = [
        {
            "node_id": "z" * 64,
            "label": "terminal-only-failure",
            "count": 7,
            "error_event_count": 0,
            "terminal_failure_count": 7,
            "trace_count": 7,
        }
    ]

    # Act
    html = render_html(report)

    # Assert
    assert '<th scope="col">Error events</th>' in html
    assert '<th scope="col">Terminal failures</th>' in html
    assert '<th scope="col">Traces</th>' in html
    assert "<td>terminal-only-failure</td><td>0</td><td>7</td><td>7</td>" in html


def test_empty_and_malformed_optional_report_sections_render_safely() -> None:
    # Arrange
    report = _report()
    report.update({"nodes": "invalid", "transitions": [{"weight": "bad"}], "metrics": []})
    html_report = report | {"transitions": "invalid"}

    # Act
    html = render_html(html_report)
    svg = render_svg(report)

    # Assert
    assert "No transitions available" in html
    assert "No metric summaries available" in html
    assert ET.fromstring(svg).tag.endswith("svg")


def test_json_serialization_is_stable_utf8_and_script_safe() -> None:
    # Arrange
    report = {"z": "Привет", "a": "</script>&", "separators": "line\u2028paragraph\u2029"}

    # Act
    serialized = serialize_analysis(report)
    embedded = serialize_embedded_analysis(report)

    # Assert
    assert serialized == (
        '{\n  "a": "</script>&",\n  "separators": "line\u2028paragraph\u2029",\n'
        '  "z": "Привет"\n}\n'
    )
    assert "</script>" not in embedded
    assert "\\u003c/script\\u003e\\u0026" in embedded
    assert "\u2028" not in embedded and "\u2029" not in embedded
    assert "\\u2028" in embedded and "\\u2029" in embedded
    assert json.loads(embedded) == report


def test_json_serialization_rejects_non_finite_numbers() -> None:
    # Arrange
    report = {"invalid": float("inf")}

    # Act / Assert
    with pytest.raises(ValueError, match="Out of range"):
        serialize_analysis(report)
    with pytest.raises(ValueError, match="Out of range"):
        serialize_embedded_analysis(report)


@settings(max_examples=30, deadline=None)
@given(
    component=st.text(
        alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
        min_size=1,
        max_size=80,
    )
)
def test_arbitrary_labels_never_create_new_svg_elements(component: str) -> None:
    # Arrange
    report = _report(component)

    # Act
    root = ET.fromstring(render_svg(report))

    # Assert
    forbidden = {"script", "foreignObject"}
    assert all(element.tag.rsplit("}", 1)[-1] not in forbidden for element in root.iter())
