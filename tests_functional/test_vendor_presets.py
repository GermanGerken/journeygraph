"""Black-box acceptance tests for packaged vendor presets (``--preset``, ``presets``)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests_functional.helpers import (
    CommandResult,
    assert_analysis_artifacts,
    assert_no_traceback,
    node_labels,
)

_SENSITIVE = (
    "synthetic prompt text",
    "synthetic response text",
    "synthetic-user",
    "synthetic-session",
    "synthetic failure",
    "someone@example.invalid",
    "synthetic-thread",
)


@pytest.mark.parametrize(
    ("fixture", "preset", "labels"),
    [
        (
            "langfuse_observations.jsonl",
            "langfuse-observations",
            {"llm:answer", "tool:lookup-order", "internal:cache-miss", "span:handle-request"},
        ),
        (
            "langsmith_runs.jsonl",
            "langsmith-runs",
            {"chain:agent", "parser:output-parser", "tool:web-search", "llm:chat-model"},
        ),
        (
            "phoenix_spans.jsonl",
            "phoenix-spans",
            {"chain:pipeline", "tool:calculator", "decision:route", "unspecified:custom-step"},
        ),
    ],
)
def test_presets_analyze_documented_vendor_shapes(
    cli: Callable[..., CommandResult],
    fixture_dir: Path,
    tmp_path: Path,
    fixture: str,
    preset: str,
    labels: set[str],
) -> None:
    # Act
    result = cli(
        "analyze", fixture_dir / fixture, "--preset", preset, "--output-dir", tmp_path / "out"
    )

    # Assert
    result.assert_exit(0)
    analysis = assert_analysis_artifacts(tmp_path / "out")
    assert analysis["totals"]["traces"] == 3
    assert analysis["totals"]["events"] == (10 if preset == "langsmith-runs" else 9)
    found = {":".join(pair) for pair in node_labels(analysis).values()}
    assert labels <= found
    for artifact in (tmp_path / "out").iterdir():
        text = artifact.read_text(encoding="utf-8")
        for value in _SENSITIVE:
            assert value not in text


def test_presets_command_lists_and_shows_presets(cli: Callable[..., CommandResult]) -> None:
    # Act
    listing = cli("presets")
    shown = cli("presets", "--show", "phoenix-spans")

    # Assert
    listing.assert_exit(0)
    assert "langfuse-observations (experimental)" in listing.stdout
    assert "phoenix-spans (experimental)" in listing.stdout
    assert "https://langfuse.com/docs/" in listing.stdout
    shown.assert_exit(0)
    assert shown.stdout.startswith("# JourneyGraph preset: phoenix-spans (experimental)")
    assert 'trace_id = "context.trace_id"' in shown.stdout


def test_a_shown_preset_works_as_a_mapping_file(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    mapping = tmp_path / "langfuse.toml"
    mapping.write_text(cli("presets", "--show", "langfuse-observations").stdout, encoding="utf-8")

    # Act
    result = cli("validate", fixture_dir / "langfuse_observations.jsonl", "--mapping", mapping)

    # Assert
    result.assert_exit(0)
    assert "valid: 9 event(s), 3 trace(s)" in result.stdout


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("--preset", "nope"), "unknown preset 'nope'"),
        (("--preset", "phoenix-spans", "--mapping", "x.toml"), "not allowed with argument"),
        (("--preset", "phoenix-spans", "--format", "otlp-json"), "OTLP input format"),
    ],
)
def test_invalid_preset_usage_is_rejected_without_artifacts(
    cli: Callable[..., CommandResult],
    fixture_dir: Path,
    tmp_path: Path,
    arguments: tuple[str, ...],
    message: str,
) -> None:
    # Act
    result = cli(
        "analyze",
        fixture_dir / "phoenix_spans.jsonl",
        *arguments,
        "--output-dir",
        tmp_path / "out",
    )

    # Assert
    result.assert_exit(2)
    assert message in result.stderr
    assert not (tmp_path / "out").exists()
    assert_no_traceback(result)


def test_unknown_preset_in_presets_show_is_a_usage_error(
    cli: Callable[..., CommandResult],
) -> None:
    result = cli("presets", "--show", "nope")
    result.assert_exit(2)
    assert "choose one of langfuse-observations, langsmith-runs, phoenix-spans" in result.stderr
