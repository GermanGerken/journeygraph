"""Black-box acceptance tests for OpenTelemetry Collector file-exporter JSON Lines input."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tests_functional.helpers import (
    CommandResult,
    assert_analysis_artifacts,
    assert_no_traceback,
    read_jsonl,
    warning_codes,
)


def test_collector_jsonl_matches_the_equivalent_otlp_json_request(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange: collector_export.otlp.jsonl holds the spans of otlp_trace.json, one per line.

    # Act
    lines = cli(
        "analyze",
        fixture_dir / "collector_export.otlp.jsonl",
        "--format",
        "otlp-jsonl",
        "--output-dir",
        tmp_path / "lines",
    )
    single = cli(
        "analyze",
        fixture_dir / "otlp_trace.json",
        "--format",
        "otlp-json",
        "--output-dir",
        tmp_path / "single",
    )

    # Assert
    lines.assert_exit(0)
    single.assert_exit(0)
    from_lines = assert_analysis_artifacts(tmp_path / "lines")
    from_single = assert_analysis_artifacts(tmp_path / "single")
    assert from_lines["paths"] == from_single["paths"]
    assert from_lines["nodes"] == from_single["nodes"]
    assert "otlp_chronological_adjacency" in warning_codes(from_lines)
    assert read_jsonl(tmp_path / "lines" / "normalized.jsonl") == read_jsonl(
        tmp_path / "single" / "normalized.jsonl"
    )


def test_malformed_collector_line_is_a_format_error(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange
    path = tmp_path / "export.jsonl"
    path.write_text('{"resourceSpans": []}\n{broken\n', encoding="utf-8")

    # Act
    result = cli("validate", path, "--format", "otlp-jsonl")

    # Assert
    result.assert_exit(2)
    assert "malformed_otlp_jsonl" in result.stderr
    assert "line 2" in result.stderr
    assert_no_traceback(result)
