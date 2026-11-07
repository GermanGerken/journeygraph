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


def test_html_uses_neutral_chronological_labels_and_shows_unknown_outcomes() -> None:
    # Arrange
    report = _report()
    report["outcomes"] = {"counts": {"success": 0, "unknown": 1}}

    # Act
    html = render_html(report)

    # Assert
    assert "Chronological paths" in html
    assert "Chronological adjacency transitions" in html
    assert "<span>Unknown</span><strong>1</strong>" in html


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


def test_findings_and_category_table_escape_hostile_text() -> None:
    # Arrange
    hostile = "<img src=x onerror=alert(1)>"
    report = _report(hostile)
    node = report["nodes"][0]  # type: ignore[index]
    node.update(
        {
            "trace_count": 4,
            "event_count": 5,
            "error_event_count": 2,
            "metrics": {"duration_ms": {"p50": 3, "p95": 9}, "cost_usd": {"count": 2, "sum": 0.5}},
            "trace_outcomes": {"counts": {"success": 1, "failure": 2, "unknown": 1}},
        }
    )
    report["findings"] = {
        "config": {"min_support": 3, "max_items": 10},
        "items": [
            {
                "kind": "error_hotspot",
                "statement": f"40% of tool:{hostile} events had error status.",
                "support": 5,
                "baseline": 0.1,
                "interval": {"low": 0.118, "high": 0.769},
                "support_level": "low",
            }
        ],
    }

    # Act
    html = render_html(report)

    # Assert
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<td>error hotspot</td><td>5</td><td>10%</td><td>12% to 77%</td><td>low</td>" in html
    assert "<td>4</td><td>5</td><td>2 (40%)</td><td>3</td><td>9</td><td>0.5</td>" in html
    assert "<td>1 of 3 (33%)</td><td>1</td>" in html
    assert html.index('id="findings"') < html.index('id="graph"') < html.index('id="categories"')


def test_findings_section_has_explicit_empty_states() -> None:
    # Arrange
    with_config = _report() | {"findings": {"config": {"min_support": 7}, "items": []}}
    without = _report()

    # Act / Assert
    assert "No observation met the minimum support of 7" in render_html(with_config)
    assert "No findings are available in this analysis." in render_html(without)


def test_category_table_handles_missing_statistics() -> None:
    # Arrange
    report = _report()
    report["nodes"] = [{"id": "b", "label": "tool:bare"}, {"id": "a", "label": "tool:zero"}]

    # Act
    html = render_html(report)

    # Assert
    bare_row = "".join(
        f"<td>{cell}</td>" for cell in ("tool:bare", 0, 0, "—", "—", "—", "—", "—", 0)
    )
    assert bare_row in html
