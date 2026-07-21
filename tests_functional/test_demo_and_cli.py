from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tests_functional.helpers import (
    ANALYSIS_ARTIFACTS,
    CommandResult,
    assert_analysis_artifacts,
    inspect_safe_svg,
    inspect_static_html,
    outcome_counts,
    read_jsonl,
    totals,
)


def test_help_documents_the_public_offline_workflow(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange
    working_directory = tmp_path / "unrelated-working-directory"
    working_directory.mkdir()

    # Act
    result = cli("--help", cwd=working_directory)

    # Assert
    result.assert_exit(0)
    assert not result.stderr.strip(), result.stderr
    help_text = result.stdout.lower()
    for command in ("validate", "analyze", "demo"):
        assert command in help_text
    for input_format in ("jsonl", "csv", "parquet", "otlp-json"):
        assert input_format in help_text
    for artifact in ANALYSIS_ARTIFACTS:
        assert artifact in help_text
    for exit_code in ("0", "1", "2", "3", "4"):
        assert exit_code in help_text


def test_demo_is_complete_deterministic_and_revalidatable(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange
    first_output = tmp_path / "demo-one"
    second_output = tmp_path / "demo-two"

    # Act
    first_result = cli("demo", "--output-dir", first_output)
    second_result = cli("demo", "--output-dir", second_output)

    # Assert
    first_result.assert_exit(0)
    second_result.assert_exit(0)
    assert not first_result.stderr.strip(), first_result.stderr
    assert not second_result.stderr.strip(), second_result.stderr
    first_analysis = assert_analysis_artifacts(first_output)
    second_analysis = assert_analysis_artifacts(second_output)
    assert first_analysis == second_analysis
    assert totals(first_analysis)["events"] > totals(first_analysis)["traces"] >= 2
    assert sum(outcome_counts(first_analysis).values()) == totals(first_analysis)["traces"]
    assert first_analysis["paths"]
    assert first_analysis["transitions"]
    assert first_analysis["retries"]
    assert first_analysis["loops"]

    for artifact in ANALYSIS_ARTIFACTS:
        assert (first_output / artifact).read_bytes() == (second_output / artifact).read_bytes()
    inspect_static_html(first_output / "report.html")
    inspect_safe_svg(first_output / "graph.svg")

    source_candidates = [
        path for path in first_output.glob("*.jsonl") if path.name != "normalized.jsonl"
    ]
    assert len(source_candidates) == 1, "demo must publish its synthetic source dataset"
    assert read_jsonl(source_candidates[0])

    # Act
    revalidation = cli("validate", source_candidates[0])

    # Assert
    revalidation.assert_exit(0)
    assert not revalidation.stderr.strip(), revalidation.stderr
