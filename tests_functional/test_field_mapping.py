"""Black-box acceptance tests for declarative TOML field mappings (``--mapping``)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests_functional.helpers import (
    CommandResult,
    assert_analysis_artifacts,
    assert_no_traceback,
    read_jsonl,
    warning_codes,
)

_IGNORED = "unmapped_source_fields_ignored"


def _without_mapping_warning(analysis: dict[str, Any]) -> dict[str, Any]:
    result = dict(analysis)
    result["warnings"] = [item for item in analysis["warnings"] if item["code"] != _IGNORED]
    result["totals"] = {**analysis["totals"], "warnings": len(result["warnings"])}
    return result


@pytest.mark.parametrize(
    ("export", "mapping"),
    [
        ("mapped_export.jsonl", "mapped_export.mapping.toml"),
        ("mapped_export.csv", "mapped_export.csv.mapping.toml"),
    ],
)
def test_mapped_export_analysis_equals_the_canonical_analysis(
    cli: Callable[..., CommandResult],
    fixture_dir: Path,
    tmp_path: Path,
    export: str,
    mapping: str,
) -> None:
    # Arrange: both exports describe the same five synthetic traces as mapped_canonical.jsonl.

    # Act
    mapped = cli(
        "analyze",
        fixture_dir / export,
        "--mapping",
        fixture_dir / mapping,
        "--output-dir",
        tmp_path / "mapped",
    )
    canonical = cli(
        "analyze", fixture_dir / "mapped_canonical.jsonl", "--output-dir", tmp_path / "canonical"
    )

    # Assert
    mapped.assert_exit(0)
    canonical.assert_exit(0)
    from_mapping = assert_analysis_artifacts(tmp_path / "mapped")
    from_canonical = assert_analysis_artifacts(tmp_path / "canonical")
    assert _without_mapping_warning(from_mapping) == from_canonical
    assert read_jsonl(tmp_path / "mapped" / "normalized.jsonl") == read_jsonl(
        tmp_path / "canonical" / "normalized.jsonl"
    )


def test_unmapped_source_fields_are_counted_but_never_emitted(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange: every nested record carries a synthetic prompt that the mapping does not read.

    # Act
    result = cli(
        "analyze",
        fixture_dir / "mapped_export.jsonl",
        "--mapping",
        fixture_dir / "mapped_export.mapping.toml",
        "--output-dir",
        tmp_path / "out",
    )

    # Assert
    result.assert_exit(0)
    analysis = assert_analysis_artifacts(tmp_path / "out")
    assert _IGNORED in warning_codes(analysis)
    assert "1 distinct source field path(s)" in result.stdout
    for artifact in (tmp_path / "out").iterdir():
        text = artifact.read_text(encoding="utf-8")
        assert "synthetic prompt text" not in text
        assert "llm.prompt" not in text
        assert "tool.name" not in text


def test_validate_writes_mapped_canonical_events(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Act
    result = cli(
        "validate",
        fixture_dir / "mapped_export.csv",
        "--mapping",
        fixture_dir / "mapped_export.csv.mapping.toml",
        "--normalized-out",
        tmp_path / "events.jsonl",
    )
    canonical = cli(
        "validate",
        fixture_dir / "mapped_canonical.jsonl",
        "--normalized-out",
        tmp_path / "canonical.jsonl",
    )

    # Assert
    result.assert_exit(0)
    canonical.assert_exit(0)
    assert "valid: 18 event(s), 5 trace(s)" in result.stdout
    assert (tmp_path / "events.jsonl").read_bytes() == (tmp_path / "canonical.jsonl").read_bytes()


def test_mapped_sensitive_metadata_is_still_excluded(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange: a mapping that tries to retain an API key and a prompt as metadata.
    export = tmp_path / "export.jsonl"
    export.write_text(
        '{"t":"trace-1","s":"step-1","at":"2026-09-21T10:00:00Z","kind":"tool","name":"search",'
        '"ms":5,"state":"ok","done":"success","key":"synthetic-secret-value","text":"hello"}\n',
        encoding="utf-8",
    )
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        'mapping_version = "1"\n'
        "[fields]\n"
        'trace_id = "t"\nstep_id = "s"\ntimestamp = "at"\noperation_type = "kind"\n'
        'component = "name"\nduration_ms = "ms"\nstatus = "state"\noutcome = "done"\n'
        "[metadata]\n"
        'api_key = "key"\nprompt = "text"\n',  # pragma: allowlist secret
        encoding="utf-8",
    )

    # Act
    result = cli(
        "analyze",
        export,
        "--mapping",
        mapping,
        "--allow-metadata-key",
        "api_key",
        "--output-dir",
        tmp_path / "out",
    )

    # Assert
    result.assert_exit(0)
    assert_analysis_artifacts(tmp_path / "out")
    events = read_jsonl(tmp_path / "out" / "normalized.jsonl")
    assert "metadata" not in events[0] or not events[0]["metadata"]
    for artifact in (tmp_path / "out").iterdir():
        assert "synthetic-secret-value" not in artifact.read_text(encoding="utf-8")


def test_invalid_mapping_is_a_usage_error_without_artifacts(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange: the mapping omits the required component field.
    mapping = tmp_path / "mapping.toml"
    mapping.write_text(
        'mapping_version = "1"\n[fields]\ntrace_id = "a"\nstep_id = "b"\ntimestamp = "c"\n'
        'operation_type = "d"\nduration_ms = "e"\nstatus = "f"\n',
        encoding="utf-8",
    )

    # Act
    result = cli(
        "analyze",
        fixture_dir / "mapped_export.jsonl",
        "--mapping",
        mapping,
        "--output-dir",
        tmp_path / "out",
    )

    # Assert
    result.assert_exit(2)
    assert "required field(s) not mapped: component" in result.stderr
    assert not (tmp_path / "out").exists()
    assert_no_traceback(result)


def test_missing_source_values_report_the_source_path(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange: the CSV mapping applied to the nested JSONL export finds no session_id.

    # Act
    result = cli(
        "validate",
        fixture_dir / "mapped_export.jsonl",
        "--mapping",
        fixture_dir / "mapped_export.csv.mapping.toml",
    )

    # Assert
    result.assert_exit(2)
    assert "[mapped_field_missing] line 1.trace_id" in result.stderr
    assert "'session_id'" in result.stderr
    assert_no_traceback(result)


@pytest.mark.parametrize(
    ("arguments", "code", "message"),
    [
        (("--format", "otlp-json"), 2, "cannot be combined with an OTLP input format"),
        (("--mapping-missing",), 3, "cannot read mapping file"),
    ],
)
def test_mapping_usage_and_file_errors(
    cli: Callable[..., CommandResult],
    fixture_dir: Path,
    tmp_path: Path,
    arguments: tuple[str, ...],
    code: int,
    message: str,
) -> None:
    # Arrange
    mapping = fixture_dir / "mapped_export.mapping.toml"
    extra: tuple[object, ...] = arguments
    if arguments == ("--mapping-missing",):
        mapping, extra = tmp_path / "absent.toml", ()

    # Act
    result = cli("validate", fixture_dir / "otlp_trace.json", "--mapping", mapping, *extra)

    # Assert
    result.assert_exit(code)
    assert message in result.stderr
    assert_no_traceback(result)
