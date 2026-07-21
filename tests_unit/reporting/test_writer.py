from __future__ import annotations

from pathlib import Path

import pytest

from journeygraph.domain import SourceRecord
from journeygraph.exceptions import FileOperationError, OutputConflictError
from journeygraph.normalization import normalize_records
from journeygraph.reporting.writer import (
    validate_output_path,
    write_analysis_artifacts,
    write_text_file,
)


def _dataset():  # type: ignore[no-untyped-def]
    record = SourceRecord(
        {
            "schema_version": "1.0",
            "trace_id": "trace-1",
            "step_id": "step-1",
            "timestamp": "2026-07-21T12:00:00Z",
            "operation_type": "request",
            "component": "entry",
            "duration_ms": 1,
            "status": "ok",
            "outcome": "success",
        },
        "line 1",
        0,
    )
    return normalize_records((record,), input_format="jsonl")


def _report() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "tool_version": "0.1.0",
        "nodes": [],
        "transitions": [],
        "totals": {"events": 1, "traces": 1},
        "outcomes": {"counts": {"success": 1}},
    }


def test_writer_publishes_fixed_artifacts_and_extra_file_atomically(tmp_path: Path) -> None:
    # Arrange
    output = tmp_path / "report"

    # Act
    artifacts = write_analysis_artifacts(
        _report(), _dataset(), output, extra_files={"source.jsonl": "{}\n"}
    )

    # Assert
    assert {path.name for path in output.iterdir()} == {
        "analysis.json",
        "normalized.jsonl",
        "report.html",
        "graph.svg",
        "source.jsonl",
    }
    assert artifacts.extra_files == (output / "source.jsonl",)
    assert artifacts.analysis_json.read_text(encoding="utf-8").endswith("\n")


def test_writer_refuses_nonempty_traversal_symlink_and_unsafe_extra_names(tmp_path: Path) -> None:
    # Arrange
    output = tmp_path / "report"
    output.mkdir()
    (output / "owner.txt").write_text("owner", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.symlink_to(output, target_is_directory=True)

    # Act / Assert
    with pytest.raises(OutputConflictError, match="not empty"):
        write_analysis_artifacts(_report(), _dataset(), output)
    with pytest.raises(OutputConflictError, match="unsafe"):
        validate_output_path(tmp_path / "safe" / ".." / "escape")
    with pytest.raises(OutputConflictError, match="symbolic link"):
        validate_output_path(linked)
    with pytest.raises(OutputConflictError, match="extra artifact"):
        write_analysis_artifacts(
            _report(), _dataset(), tmp_path / "new", extra_files={"../bad": "x"}
        )
    with pytest.raises(OutputConflictError, match="extra artifact"):
        write_analysis_artifacts(
            _report(), _dataset(), tmp_path / "new", extra_files={"analysis.json": "x"}
        )


def test_text_writer_requires_force_and_never_overwrites_input(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "source.jsonl"
    source.write_text("original", encoding="utf-8")
    output = tmp_path / "output.jsonl"
    output.write_text("owner", encoding="utf-8")

    # Act / Assert
    with pytest.raises(OutputConflictError, match="already exists"):
        write_text_file(output, "new", force=False)
    with pytest.raises(OutputConflictError, match="input file"):
        write_text_file(source, "new", force=True, input_path=source)
    written = write_text_file(output, "new", force=True)
    assert written.read_text(encoding="utf-8") == "new"


def test_analysis_writer_rejects_input_artifact_collision_even_with_force(tmp_path: Path) -> None:
    # Arrange
    output = tmp_path / "report"
    output.mkdir()
    colliding_input = output / "analysis.json"
    colliding_input.write_text("input", encoding="utf-8")

    # Act
    with pytest.raises(OutputConflictError, match="collision"):
        write_analysis_artifacts(
            _report(),
            _dataset(),
            output,
            force=True,
            input_path=colliding_input,
        )

    # Assert
    assert colliding_input.read_text(encoding="utf-8") == "input"


def test_writer_rejects_case_insensitive_input_aliases(tmp_path: Path) -> None:
    # Arrange
    validate_input = tmp_path / "Normalized.JSONL"
    validate_input.write_text("validate input", encoding="utf-8")
    validate_alias = tmp_path / "normalized.jsonl"
    if not validate_alias.exists():
        pytest.skip("the temporary filesystem is case-sensitive")
    original_validate = validate_input.read_bytes()

    analysis_dir = tmp_path / "analysis"
    analysis_dir.mkdir()
    analysis_input = analysis_dir / "Analysis.JSON"
    analysis_input.write_text("analysis input", encoding="utf-8")
    original_analysis = analysis_input.read_bytes()

    # Act / Assert
    with pytest.raises(OutputConflictError, match="input file"):
        write_text_file(
            validate_alias,
            "replacement",
            force=True,
            input_path=validate_input,
        )
    with pytest.raises(OutputConflictError, match="collision"):
        write_analysis_artifacts(
            _report(),
            _dataset(),
            analysis_dir,
            force=True,
            input_path=analysis_input,
        )
    assert validate_input.read_bytes() == original_validate
    assert analysis_input.read_bytes() == original_analysis


def test_text_writer_cleans_temporary_file_after_unicode_encoding_failure(tmp_path: Path) -> None:
    # Arrange
    output = tmp_path / "output.txt"

    # Act / Assert
    with pytest.raises(FileOperationError, match="cannot write"):
        write_text_file(output, chr(0xD800), force=False)
    assert list(tmp_path.iterdir()) == []
