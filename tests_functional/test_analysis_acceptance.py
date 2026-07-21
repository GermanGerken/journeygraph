from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests_functional.helpers import (
    CommandResult,
    analysis_meaning,
    artifact_text,
    assert_analysis_artifacts,
    inspect_safe_svg,
    inspect_static_html,
    node_labels,
    outcome_counts,
    path_counts,
    read_jsonl,
    totals,
    transition_counts,
    warning_codes,
)

NodeLabel = tuple[str, str]


def _analyze(
    cli: Callable[..., CommandResult], input_path: Path, output_dir: Path
) -> dict[str, Any]:
    result = cli("analyze", input_path, "--output-dir", output_dir)
    result.assert_exit(0)
    assert not result.stderr.strip(), result.stderr
    return assert_analysis_artifacts(output_dir)


def _node_sequence(
    analysis: dict[str, Any], records: list[dict[str, Any]]
) -> list[tuple[NodeLabel, ...]]:
    labels = node_labels(analysis)
    sequences: list[tuple[NodeLabel, ...]] = []
    for record in records:
        node_ids = record.get("node_ids")
        assert isinstance(node_ids, list) and node_ids
        assert all(node_id in labels for node_id in node_ids)
        sequences.append(tuple(labels[node_id] for node_id in node_ids))
    return sequences


def _point_labels(analysis: dict[str, Any], section: str) -> set[NodeLabel]:
    labels = node_labels(analysis)
    records = analysis.get(section)
    assert isinstance(records, list)
    result: set[NodeLabel] = set()
    for record in records:
        assert isinstance(record, dict)
        node_id = record.get("node_id", record.get("id"))
        assert node_id in labels
        count = record.get("trace_count", record.get("count"))
        assert isinstance(count, int) and count > 0
        result.add(labels[node_id])
    return result


def test_linear_trace_validates_and_produces_semantic_reports(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "linear.jsonl"
    validated_path = tmp_path / "validated.jsonl"
    output_dir = tmp_path / "linear-report"

    # Act
    validation = cli("validate", input_path, "--normalized-out", validated_path)
    analysis = _analyze(cli, input_path, output_dir)

    # Assert
    validation.assert_exit(0)
    assert not validation.stderr.strip(), validation.stderr
    assert re.search(r"\b3\b.*event", validation.stdout, re.IGNORECASE | re.DOTALL)
    assert re.search(r"\b1\b.*trace", validation.stdout, re.IGNORECASE | re.DOTALL)

    normalized = read_jsonl(validated_path)
    assert [record["step_id"] for record in normalized] == ["s1", "s2", "s3"]
    assert all(record["timestamp"].endswith("Z") for record in normalized)
    assert totals(analysis)["events"] == 3
    assert totals(analysis)["traces"] == 1
    assert outcome_counts(analysis)["success"] == 1

    expected_nodes: tuple[NodeLabel, ...] = (
        ("request", "User request"),
        ("router", "Intent router"),
        ("outcome", "Completed"),
    )
    assert set(node_labels(analysis).values()) == set(expected_nodes)
    assert transition_counts(analysis) == {
        (expected_nodes[0], expected_nodes[1]): (1, 1),
        (expected_nodes[1], expected_nodes[2]): (1, 1),
    }
    assert path_counts(analysis) == {
        expected_nodes: (1, {"success": 1}),
    }
    assert _point_labels(analysis, "entries") == {expected_nodes[0]}
    assert _point_labels(analysis, "terminals") == {expected_nodes[-1]}

    html = inspect_static_html(output_dir / "report.html")
    report_text = " ".join(html.text.split()).lower()
    for concept in ("journeygraph", "path", "transition", "outcome", "association"):
        assert concept in report_text
    svg = inspect_safe_svg(output_dir / "graph.svg")
    svg_text = "".join(svg.itertext())
    assert all(component in svg_text for _, component in expected_nodes)


def test_branching_paths_reconcile_success_and_failure(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "branching.jsonl"
    output_dir = tmp_path / "branching-report"

    # Act
    analysis = _analyze(cli, input_path, output_dir)

    # Assert
    request = ("request", "User request")
    router = ("router", "Intent router")
    completed = ("outcome", "Completed")
    failed_tool = ("tool", "Database tool")

    assert totals(analysis)["events"] == 6
    assert totals(analysis)["traces"] == 2
    outcomes = outcome_counts(analysis)
    assert outcomes["success"] == 1
    assert outcomes["failure"] == 1
    assert sum(outcomes.values()) == 2
    assert transition_counts(analysis) == {
        (request, router): (2, 2),
        (router, completed): (1, 1),
        (router, failed_tool): (1, 1),
    }
    assert path_counts(analysis) == {
        (request, router, completed): (1, {"success": 1}),
        (request, router, failed_tool): (1, {"failure": 1}),
    }
    assert _point_labels(analysis, "failure_points") == {failed_tool}

    path_comparison = analysis["path_comparison"]
    assert isinstance(path_comparison, list)
    encoded = json.dumps(path_comparison, ensure_ascii=False).lower()
    assert "success" in encoded and ("non_success" in encoded or "non-success" in encoded)


def test_retry_and_return_loop_are_counted_without_phantom_transitions(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "retry_loop.jsonl"
    output_dir = tmp_path / "retry-loop-report"

    # Act
    analysis = _analyze(cli, input_path, output_dir)

    # Assert
    request = ("request", "User request")
    search = ("tool", "Search")
    index = ("retrieval", "Index")
    generator = ("model", "Generator")
    completed = ("outcome", "Completed")
    assert outcome_counts(analysis)["success"] == 2
    assert transition_counts(analysis) == {
        (request, search): (1, 1),
        (search, search): (1, 1),
        (search, completed): (1, 1),
        (request, index): (1, 1),
        (index, generator): (1, 1),
        (generator, index): (1, 1),
        (index, completed): (1, 1),
    }

    retries = analysis["retries"]
    assert isinstance(retries, list) and len(retries) == 1
    retry = retries[0]
    assert _node_sequence(analysis, retries) == [(search,)]
    assert retry.get("count", retry.get("occurrence_count")) == 1
    assert retry["trace_count"] == 1

    loops = analysis["loops"]
    assert isinstance(loops, list) and len(loops) == 1
    loop = loops[0]
    assert _node_sequence(analysis, loops) == [(index, generator, index)]
    assert loop.get("count", loop.get("occurrence_count")) == 1
    assert loop["trace_count"] == 1


def test_handoff_dropoff_and_optional_metrics_are_exposed_across_traces(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "handoff_dropoff_metrics.jsonl"
    output_dir = tmp_path / "outcomes-and-metrics"

    # Act
    analysis = _analyze(cli, input_path, output_dir)

    # Assert
    assert outcome_counts(analysis) == {"success": 1, "handoff": 1, "dropoff": 1}
    assert _point_labels(analysis, "dropoff_points") == {("retrieval", "Documents")}
    dropoff = analysis["dropoff_points"][0]
    assert dropoff["count"] == 1
    assert dropoff["explicit_count"] == 0
    assert dropoff["inferred_count"] == 1
    assert dropoff["outcome_sources"] == [{"source": "missing", "count": 1}]

    metrics = analysis["metrics"]
    assert metrics["duration_ms"]["count"] == 6
    assert metrics["duration_ms"]["sum"] == 60
    assert metrics["input_tokens"]["count"] == 2
    assert metrics["input_tokens"]["sum"] == 10
    assert metrics["output_tokens"]["sum"] == 4
    assert metrics["total_tokens"]["sum"] == 14
    assert metrics["cost_usd"]["count"] == 2
    assert metrics["cost_usd"]["sum"] == 0.014


def test_repeated_terminal_failures_reconcile_separately_from_handoff(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "repeated_failure_handoff.jsonl"
    output_dir = tmp_path / "repeated-failure-handoff"

    # Act
    analysis = _analyze(cli, input_path, output_dir)

    # Assert
    request = ("request", "User request")
    failed_tool = ("tool", "Payment tool")
    handoff = ("human", "Support queue")
    assert outcome_counts(analysis) == {"failure": 2, "handoff": 1}
    assert transition_counts(analysis) == {
        (request, failed_tool): (2, 2),
        (request, handoff): (1, 1),
    }
    assert path_counts(analysis) == {
        (request, failed_tool): (2, {"failure": 2}),
        (request, handoff): (1, {"handoff": 1}),
    }
    failure_points = analysis["failure_points"]
    assert isinstance(failure_points, list) and len(failure_points) == 1
    failure = failure_points[0]
    assert node_labels(analysis)[failure["node_id"]] == failed_tool
    assert failure["count"] == 2
    assert failure["trace_count"] == 2
    assert failure["error_event_count"] == 2
    assert failure["terminal_failure_count"] == 2
    assert _point_labels(analysis, "terminals") == {failed_tool, handoff}
    assert analysis["metrics"]["duration_ms"]["sum"] == 40


def test_explicit_otlp_json_cli_boundary_maps_openinference_without_raw_payloads(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "otlp_trace.json"
    output_dir = tmp_path / "otlp-report"

    # Act
    implicit = cli("validate", input_path)
    explicit = cli(
        "analyze",
        input_path,
        "--format",
        "otlp-json",
        "--output-dir",
        output_dir,
    )

    # Assert
    implicit.assert_exit(2)
    assert "--format" in implicit.stderr and "otlp-json" in implicit.stderr
    explicit.assert_exit(0)
    assert not explicit.stderr.strip(), explicit.stderr

    analysis = assert_analysis_artifacts(output_dir)
    assert totals(analysis)["events"] == 2
    assert outcome_counts(analysis) == {"success": 1}
    assert set(node_labels(analysis).values()) == {
        ("agent", "Planner"),
        ("tool", "Weather API"),
    }
    assert analysis["metrics"]["input_tokens"]["sum"] == 7
    assert analysis["metrics"]["output_tokens"]["sum"] == 3
    assert analysis["metrics"]["cost_usd"]["sum"] == 0.004

    normalized = read_jsonl(output_dir / "normalized.jsonl")
    assert [record["timestamp"] for record in normalized] == [
        "2026-01-01T00:00:00.000000123Z",
        "2026-01-01T00:00:00.003000456Z",
    ]
    assert normalized[1]["parent_step_id"] == normalized[0]["step_id"]
    combined = artifact_text(output_dir)
    for sensitive_value in (
        "resource-secret-sentinel",
        "prompt-secret-sentinel",
        "tool-secret-sentinel",
    ):
        assert sensitive_value not in combined


def test_out_of_order_input_uses_stable_timestamp_and_step_id_order(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_a = fixture_dir / "out_of_order_a.jsonl"
    input_b = fixture_dir / "out_of_order_b.jsonl"
    output_a = tmp_path / "order-a"
    output_b = tmp_path / "order-b"
    output_repeat = tmp_path / "order-repeat"

    # Act
    analysis_a = _analyze(cli, input_a, output_a)
    analysis_b = _analyze(cli, input_b, output_b)
    _analyze(cli, input_a, output_repeat)

    # Assert
    normalized_a = (output_a / "normalized.jsonl").read_bytes()
    normalized_b = (output_b / "normalized.jsonl").read_bytes()
    assert normalized_a == normalized_b
    assert [record["step_id"] for record in read_jsonl(output_a / "normalized.jsonl")] == [
        "a",
        "b",
        "c",
        "d",
    ]
    assert analysis_meaning(analysis_a) == analysis_meaning(analysis_b)
    assert (output_a / "analysis.json").read_bytes() == (
        output_repeat / "analysis.json"
    ).read_bytes()

    codes = [code.lower() for code in warning_codes(analysis_a)]
    assert any("order" in code for code in codes)
    assert any("timestamp" in code or "tie" in code for code in codes)


def test_exact_duplicates_are_deduplicated_idempotently(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "duplicate_exact.jsonl"
    first_output = tmp_path / "deduplicated"
    second_output = tmp_path / "reanalyzed"

    # Act
    first = _analyze(cli, input_path, first_output)
    second = _analyze(cli, first_output / "normalized.jsonl", second_output)

    # Assert
    assert totals(first)["input_records"] == 3
    assert totals(first)["events"] == 2
    assert len(read_jsonl(first_output / "normalized.jsonl")) == 2
    assert (first_output / "normalized.jsonl").read_bytes() == (
        second_output / "normalized.jsonl"
    ).read_bytes()
    assert analysis_meaning(first) == analysis_meaning(second)
    assert any("duplicate" in code.lower() for code in warning_codes(first))


def test_conflicting_duplicate_is_actionable_and_blocks_artifacts(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "duplicate_conflict.jsonl"
    output_dir = tmp_path / "conflict-report"

    # Act
    result = cli("analyze", input_path, "--output-dir", output_dir)

    # Assert
    result.assert_exit(2)
    assert not result.stdout.strip()
    message = result.stderr.lower()
    assert "duplicate" in message and "conflict" in message
    assert "traceback (most recent call last)" not in message
    assert not (output_dir / "analysis.json").exists()
    assert not (output_dir / "report.html").exists()
