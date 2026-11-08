"""Black-box acceptance tests for binary OTLP protobuf input formats."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests_functional.helpers import (
    CommandResult,
    assert_analysis_artifacts,
    assert_no_traceback,
    read_jsonl,
    warning_codes,
)


@pytest.mark.parametrize(
    ("fixture", "input_format"),
    [("otlp_trace.pb", "otlp-proto"), ("collector_export.binpb", "otlp-proto-file")],
)
def test_binary_otlp_matches_the_equivalent_otlp_json(
    cli: Callable[..., CommandResult],
    fixture_dir: Path,
    tmp_path: Path,
    fixture: str,
    input_format: str,
) -> None:
    # Arrange: both binary fixtures encode otlp_trace.json with the official protobuf library.

    # Act
    binary = cli(
        "analyze",
        fixture_dir / fixture,
        "--format",
        input_format,
        "--output-dir",
        tmp_path / "binary",
    )
    json_result = cli(
        "analyze",
        fixture_dir / "otlp_trace.json",
        "--format",
        "otlp-json",
        "--output-dir",
        tmp_path / "json",
    )

    # Assert
    binary.assert_exit(0)
    json_result.assert_exit(0)
    from_binary = assert_analysis_artifacts(tmp_path / "binary")
    from_json = assert_analysis_artifacts(tmp_path / "json")
    assert from_binary["paths"] == from_json["paths"]
    assert from_binary["nodes"] == from_json["nodes"]
    assert "otlp_chronological_adjacency" in warning_codes(from_binary)
    assert read_jsonl(tmp_path / "binary" / "normalized.jsonl") == read_jsonl(
        tmp_path / "json" / "normalized.jsonl"
    )


def test_binary_otlp_is_never_auto_detected(
    cli: Callable[..., CommandResult], fixture_dir: Path
) -> None:
    result = cli("validate", fixture_dir / "otlp_trace.pb")
    result.assert_exit(2)
    assert "otlp-proto" in result.stderr
    assert_no_traceback(result)


def test_truncated_collector_file_is_a_format_error(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    data = (fixture_dir / "collector_export.binpb").read_bytes()
    path = tmp_path / "export.binpb"
    path.write_bytes(data[:-3])

    # Act
    result = cli("validate", path, "--format", "otlp-proto-file")

    # Assert
    result.assert_exit(2)
    assert "malformed_otlp_proto" in result.stderr
    assert "message length exceeds the file" in result.stderr
    assert_no_traceback(result)
