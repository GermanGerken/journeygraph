"""Black-box acceptance tests for ranked findings and the readable report."""

from __future__ import annotations

import random
from collections.abc import Callable
from pathlib import Path

import pytest

from tests_functional.helpers import (
    CommandResult,
    assert_analysis_artifacts,
    assert_no_traceback,
    inspect_safe_svg,
    inspect_static_html,
    read_json,
)

FIXTURE = "findings_association.jsonl"


def _findings(analysis: dict[str, object]) -> list[tuple[str, str, int]]:
    findings = analysis["findings"]
    assert isinstance(findings, dict)
    items = findings["items"]
    assert isinstance(items, list)
    return [(item["kind"], item["label"], item["support"]) for item in items]


def test_analyze_ranks_hand_computed_findings(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange: 10 answered traces via retrieval, 8 failing payment traces with tool errors,
    # and 4 retrieval-retry traces without an outcome; model:llm dominates duration and cost.
    output_dir = tmp_path / "report"

    # Act
    result = cli("analyze", fixture_dir / FIXTURE, "--output-dir", output_dir)

    # Assert
    result.assert_exit(0)
    analysis = assert_analysis_artifacts(output_dir)
    assert analysis["findings"]["config"] == {"min_support": 3, "max_items": 10}
    assert _findings(analysis) == [
        ("outcome_association", "retrieval:docs", 10),
        ("outcome_association", "tool:payments", 8),
        ("error_hotspot", "tool:payments", 8),
        ("duration_concentration", "model:llm", 22),
        ("cost_concentration", "model:llm", 18),
        ("retry_prevalence", "retrieval:docs", 4),
    ]
    items = analysis["findings"]["items"]
    assert items[0]["value"] == 1.0 and items[0]["baseline"] == 0.0
    assert "4 visiting trace(s) with an unknown outcome were excluded" in items[0]["statement"]
    assert items[2]["baseline"] == pytest.approx(8 / 92)
    assert items[3]["value"] == pytest.approx(22000 / 22700)
    assert "4 of its event(s) had no cost value" in items[4]["statement"]
    assert items[5]["value"] == pytest.approx(4 / 22)
    assert all(
        "cause" not in item["statement"] or "not a cause" in item["statement"] for item in items
    )

    nodes = {node["label"]: node for node in analysis["nodes"]}
    assert nodes["tool:payments"]["error_event_count"] == 8
    assert nodes["retrieval:docs"]["trace_outcomes"]["counts"] == {
        "success": 10,
        "failure": 0,
        "handoff": 0,
        "dropoff": 0,
        "unknown": 4,
    }
    assert nodes["model:llm"]["metrics"]["cost_usd"]["missing_count"] == 4

    html = inspect_static_html(output_dir / "report.html")
    assert "Key findings" in html.text
    assert "Operation categories" in html.text
    assert html.text.index("Key findings") < html.text.index("Aggregate chronological-adjacency")
    assert "8 (100%)" in html.text
    svg_text = "".join(inspect_safe_svg(output_dir / "graph.svg").itertext())
    assert "tool:payments — 8 event(s) in 8 trace(s); 8 error event(s) (100%)" in svg_text


def test_min_support_filters_findings_and_reports_empty_state(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Act
    stricter = cli(
        "analyze", fixture_dir / FIXTURE, "--output-dir", tmp_path / "a", "--min-support", "11"
    )
    none = cli(
        "analyze", fixture_dir / FIXTURE, "--output-dir", tmp_path / "b", "--min-support", "50"
    )

    # Assert
    stricter.assert_exit(0)
    none.assert_exit(0)
    assert _findings(read_json(tmp_path / "a" / "analysis.json")) == [
        ("duration_concentration", "model:llm", 22),
        ("cost_concentration", "model:llm", 18),
    ]
    assert read_json(tmp_path / "b" / "analysis.json")["findings"]["items"] == []
    html = inspect_static_html(tmp_path / "b" / "report.html")
    assert "No observation met the minimum support of 50" in html.text


@pytest.mark.parametrize("value", ["0", "-2", "three", "1.5"])
def test_invalid_min_support_is_a_usage_error(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path, value: str
) -> None:
    # Act
    result = cli(
        "analyze", fixture_dir / FIXTURE, "--output-dir", tmp_path / "out", "--min-support", value
    )

    # Assert
    result.assert_exit(2)
    assert "positive integer" in result.stderr
    assert_no_traceback(result)
    assert not (tmp_path / "out").exists()


def test_artifacts_are_byte_identical_when_traces_are_reordered(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange: shuffle whole traces, keeping each trace's own rows in order.
    lines = (fixture_dir / FIXTURE).read_text(encoding="utf-8").splitlines()
    blocks: dict[str, list[str]] = {}
    for line in lines:
        blocks.setdefault(line.split('"trace_id":"', 1)[1].split('"', 1)[0], []).append(line)
    order = sorted(blocks)
    random.Random(20261108).shuffle(order)
    shuffled = tmp_path / "shuffled.jsonl"
    shuffled.write_text("\n".join(row for key in order for row in blocks[key]) + "\n", "utf-8")

    # Act
    cli("analyze", fixture_dir / FIXTURE, "--output-dir", tmp_path / "a").assert_exit(0)
    cli("analyze", shuffled, "--output-dir", tmp_path / "b").assert_exit(0)

    # Assert
    for name in ("analysis.json", "graph.svg", "report.html", "normalized.jsonl"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name
