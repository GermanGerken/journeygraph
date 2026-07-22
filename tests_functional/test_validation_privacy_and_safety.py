from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from tests_functional.helpers import (
    ANALYSIS_ARTIFACTS,
    CommandResult,
    artifact_text,
    assert_analysis_artifacts,
    assert_no_traceback,
    inspect_safe_svg,
    inspect_static_html,
    node_labels,
    read_jsonl,
    warning_codes,
)


@pytest.mark.parametrize(
    ("fixture_name", "expected_terms"),
    [
        ("malformed.jsonl", ("json", "line")),
        ("missing_required.jsonl", ("component", "required")),
        ("invalid_numeric.jsonl", ("duration", "negative")),
        ("invalid_timestamp.jsonl", ("timestamp", "offset")),
        ("invalid_status.jsonl", ("status", "unset")),
        ("invalid_nan.jsonl", ("duration", "finite")),
        ("invalid_infinity.jsonl", ("duration", "finite")),
        ("missing_required.csv", ("csv", "component", "required")),
        ("empty.jsonl", ("empty",)),
    ],
)
def test_invalid_input_is_concise_and_never_publishes_partial_output(
    cli: Callable[..., CommandResult],
    fixture_dir: Path,
    tmp_path: Path,
    fixture_name: str,
    expected_terms: tuple[str, ...],
) -> None:
    # Arrange
    input_path = fixture_dir / fixture_name
    normalized_out = tmp_path / f"{input_path.stem}-normalized.jsonl"

    # Act
    result = cli("validate", input_path, "--normalized-out", normalized_out)

    # Assert
    result.assert_exit(2)
    assert not result.stdout.strip()
    assert result.stderr.strip()
    assert_no_traceback(result)
    message = result.stderr.lower()
    assert all(term in message for term in expected_terms)
    assert not normalized_out.exists()


def test_validate_requires_force_before_replacing_an_existing_output(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "linear.jsonl"
    normalized_out = tmp_path / "normalized.jsonl"
    original = b"owner data must not be replaced implicitly\n"
    normalized_out.write_bytes(original)

    # Act
    refused = cli("validate", input_path, "--normalized-out", normalized_out)

    # Assert
    refused.assert_exit(4)
    assert_no_traceback(refused)
    assert normalized_out.read_bytes() == original
    assert "force" in refused.stderr.lower() or "exists" in refused.stderr.lower()

    # Act
    forced = cli("validate", input_path, "--normalized-out", normalized_out, "--force")

    # Assert
    forced.assert_exit(0)
    assert not forced.stderr.strip(), forced.stderr
    assert [record["step_id"] for record in read_jsonl(normalized_out)] == ["s1", "s2", "s3"]


def test_validate_rejects_parent_traversal_for_normalized_output(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "linear.jsonl"
    unsafe_output = tmp_path / "safe-parent" / ".." / "escaped.jsonl"

    # Act
    result = cli("validate", input_path, "--normalized-out", str(unsafe_output), "--force")

    # Assert
    result.assert_exit(4)
    assert_no_traceback(result)
    assert ".." in result.stderr or "unsafe" in result.stderr.lower()
    assert not (tmp_path / "escaped.jsonl").exists()


def test_validate_rejects_input_output_collision_even_with_force(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = tmp_path / "input.jsonl"
    shutil.copyfile(fixture_dir / "linear.jsonl", input_path)
    original = input_path.read_bytes()

    # Act
    result = cli("validate", input_path, "--normalized-out", input_path, "--force")

    # Assert
    result.assert_exit(4)
    assert_no_traceback(result)
    assert "input" in result.stderr.lower() and "overwrite" in result.stderr.lower()
    assert input_path.read_bytes() == original


def test_missing_input_uses_documented_io_exit_code(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange
    missing_input = tmp_path / "missing.jsonl"

    # Act
    result = cli("validate", missing_input)

    # Assert
    result.assert_exit(3)
    assert not result.stdout.strip()
    assert_no_traceback(result)
    assert "does not exist" in result.stderr.lower()


def test_malformed_csv_uses_validation_exit_code_without_traceback(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange
    input_path = tmp_path / "oversized-field.csv"
    input_path.write_text(
        "schema_version,trace_id,step_id,timestamp,operation_type,component,"
        "duration_ms,status\n"
        "1.0,t,s,2026-01-01T00:00:00Z,request,"
        f"{'x' * 200_000},1,ok\n",
        encoding="utf-8",
    )

    # Act
    result = cli("validate", input_path)

    # Assert
    result.assert_exit(2)
    assert not result.stdout.strip()
    assert "malformed_csv" in result.stderr
    assert_no_traceback(result)


def test_normalized_metadata_key_collisions_are_excluded(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange
    input_path = tmp_path / "metadata-collision.jsonl"
    normalized_out = tmp_path / "normalized.jsonl"
    record = {
        "schema_version": "1.0",
        "trace_id": "trace-1",
        "step_id": "step-1",
        "timestamp": "2026-01-01T00:00:00Z",
        "operation_type": "request",
        "component": "start",
        "duration_ms": 1,
        "status": "ok",
        "outcome": "success",
        "metadata": {
            "build-id": "first-private-sentinel",
            "build_id": "second-private-sentinel",
        },
    }
    input_path.write_text(f"{json.dumps(record)}\n", encoding="utf-8")

    # Act
    result = cli(
        "validate",
        input_path,
        "--allow-metadata-key",
        "build-id",
        "--normalized-out",
        normalized_out,
    )

    # Assert
    result.assert_exit(0)
    assert not result.stderr.strip(), result.stderr
    assert read_jsonl(normalized_out)[0].get("metadata", {}) == {}
    assert "metadata_key_collision" in result.stdout
    assert "private-sentinel" not in result.stdout


def test_sensitive_and_unknown_metadata_cannot_reappear_downstream(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    source_records = read_jsonl(fixture_dir / "sensitive_metadata.jsonl")
    metadata = source_records[0]["metadata"]
    assert isinstance(metadata, dict)
    metadata["prompt_PRIVATE_KEY_SENTINEL"] = "private key value"
    source_records[0]["unknown_PRIVATE_FIELD_SENTINEL"] = "private field value"
    input_path = tmp_path / "sensitive-metadata.jsonl"
    input_path.write_text(
        "".join(f"{json.dumps(record, ensure_ascii=True)}\n" for record in source_records),
        encoding="utf-8",
    )
    output_dir = tmp_path / "privacy-report"
    attempted_allowlist = (
        "prompt",
        "response",
        "email",
        "authorization",
        "api_key",
        "password",
        "cookie",
        "customer_id",
        "username",
    )
    sensitive_values = (
        "private prompt text",
        "private response text",
        "person@example.invalid",
        "private authorization value",
        "private api key value",
        "private password value",
        "private cookie value",
        "private customer identifier",
        "private username",
        "private unknown metadata",
        "private nested payload",
        "private key value",
        "private field value",
    )
    arguments: list[str | Path] = [
        "analyze",
        input_path,
        "--output-dir",
        output_dir,
        "--cohort-key",
        "agent",
    ]
    for key in attempted_allowlist:
        arguments.extend(("--allow-metadata-key", key))

    # Act
    result = cli(*arguments)

    # Assert
    result.assert_exit(0)
    assert not result.stderr.strip(), result.stderr
    analysis = assert_analysis_artifacts(output_dir)
    combined_artifacts = artifact_text(output_dir)
    assert all(value not in combined_artifacts for value in sensitive_values)
    assert "PRIVATE_KEY_SENTINEL" not in combined_artifacts
    assert "PRIVATE_FIELD_SENTINEL" not in combined_artifacts
    assert "PRIVATE_KEY_SENTINEL" not in result.stdout
    assert "PRIVATE_FIELD_SENTINEL" not in result.stdout

    normalized = read_jsonl(output_dir / "normalized.jsonl")
    assert normalized[0]["metadata"] == {"agent": "safe-agent"}
    assert "raw_payload" not in normalized[0]
    assert "safe-agent" in json.dumps(analysis["cohorts"], ensure_ascii=False)
    codes = [code.lower() for code in warning_codes(analysis)]
    assert any("sensitive" in code or "metadata" in code for code in codes)


def test_untrusted_labels_are_text_not_executable_html_or_svg(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "injection.jsonl"
    output_dir = tmp_path / "injection-report"
    hostile_component = (
        "</text><script id='jg-pwn'>globalThis.jgPwned=1</script>"
        "<text onload='jgPwned=2'>& \"quoted\""
    )

    # Act
    result = cli(
        "analyze",
        input_path,
        "--output-dir",
        output_dir,
        "--cohort-key",
        "cohort",
    )

    # Assert
    result.assert_exit(0)
    analysis = assert_analysis_artifacts(output_dir)
    assert any(component == hostile_component for _, component in node_labels(analysis).values())

    html = inspect_static_html(output_dir / "report.html")
    assert "globalThis.jgPwned=1" in html.text
    assert "jg-pwn" not in {
        value for _, name, value in html.attributes if name == "id" and value is not None
    }

    svg = inspect_safe_svg(output_dir / "graph.svg")
    assert "globalThis.jgPwned=1" in "".join(svg.itertext())
    assert "globalThis.jgPwned=3" not in {
        value for element in svg.iter() for value in element.attrib.values()
    }


def test_unicode_labels_and_metadata_remain_valid_utf8(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "unicode.jsonl"
    output_dir = tmp_path / "unicode-report"
    expected_labels = {
        "Запрос пользователя 👋",
        "Génération — 東京 🤖",
        "Успех ✅",
    }

    # Act
    result = cli(
        "analyze",
        input_path,
        "--output-dir",
        output_dir,
        "--cohort-key",
        "region",
    )

    # Assert
    result.assert_exit(0)
    analysis = assert_analysis_artifacts(output_dir)
    assert expected_labels == {component for _, component in node_labels(analysis).values()}
    combined = artifact_text(output_dir)
    assert all(label in combined for label in expected_labels)
    assert "São Paulo" in combined
    normalized = read_jsonl(output_dir / "normalized.jsonl")
    assert [record["timestamp"] for record in normalized] == [
        "2026-07-21T12:00:00.000000Z",
        "2026-07-21T12:00:01.000000Z",
        "2026-07-21T12:00:02.000000Z",
    ]


def test_existing_nonempty_output_requires_force_and_is_not_touched(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "linear.jsonl"
    output_dir = tmp_path / "existing-report"
    output_dir.mkdir()
    marker = output_dir / "owner-data.txt"
    marker.write_text("must remain unchanged", encoding="utf-8")

    # Act
    refused = cli("analyze", input_path, "--output-dir", output_dir)

    # Assert
    refused.assert_exit(4)
    assert_no_traceback(refused)
    message = refused.stderr.lower()
    assert "overwrite" in message or "non-empty" in message or "not empty" in message
    assert marker.read_text(encoding="utf-8") == "must remain unchanged"
    assert not any((output_dir / name).exists() for name in ANALYSIS_ARTIFACTS)

    # Act
    forced = cli("analyze", input_path, "--output-dir", output_dir, "--force")

    # Assert
    forced.assert_exit(0)
    assert_analysis_artifacts(output_dir)
    assert marker.read_text(encoding="utf-8") == "must remain unchanged"


def test_output_path_with_parent_traversal_is_rejected(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "linear.jsonl"
    unsafe_output = tmp_path / "safe-parent" / ".." / "escaped-report"
    resolved_escape = tmp_path / "escaped-report"

    # Act
    result = cli("analyze", input_path, "--output-dir", str(unsafe_output))

    # Assert
    result.assert_exit(4)
    assert_no_traceback(result)
    assert ".." in result.stderr or "unsafe" in result.stderr.lower()
    assert not resolved_escape.exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_symlink_output_root_is_rejected(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    input_path = fixture_dir / "linear.jsonl"
    actual_directory = tmp_path / "actual"
    actual_directory.mkdir()
    linked_directory = tmp_path / "linked"
    try:
        linked_directory.symlink_to(actual_directory, target_is_directory=True)
    except OSError as error:  # pragma: no cover - platform policy, not product behavior
        pytest.skip(f"cannot create a test symlink: {error}")

    # Act
    result = cli("analyze", input_path, "--output-dir", linked_directory, "--force")

    # Assert
    result.assert_exit(4)
    assert_no_traceback(result)
    assert "symlink" in result.stderr.lower() or "unsafe" in result.stderr.lower()
    assert not any((actual_directory / name).exists() for name in ANALYSIS_ARTIFACTS)


def test_input_artifact_collision_is_rejected_even_with_force(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    collision_dir = tmp_path / "collision"
    collision_dir.mkdir()
    colliding_input = collision_dir / "analysis.json"
    shutil.copyfile(fixture_dir / "linear.jsonl", colliding_input)
    original = colliding_input.read_bytes()

    # Act
    result = cli(
        "analyze",
        colliding_input,
        "--format",
        "jsonl",
        "--output-dir",
        collision_dir,
        "--force",
    )

    # Assert
    result.assert_exit(4)
    assert_no_traceback(result)
    assert "input" in result.stderr.lower() and "collision" in result.stderr.lower()
    assert colliding_input.read_bytes() == original
    assert not (collision_dir / "report.html").exists()


def test_case_insensitive_input_aliases_cannot_be_overwritten(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    validate_dir = tmp_path / "validate-case-alias"
    validate_dir.mkdir()
    validate_input = validate_dir / "Normalized.JSONL"
    shutil.copyfile(fixture_dir / "linear.jsonl", validate_input)
    validate_alias = validate_dir / "normalized.jsonl"
    if not validate_alias.exists():
        pytest.skip("the temporary filesystem is case-sensitive")
    validate_original = validate_input.read_bytes()

    analysis_dir = tmp_path / "analysis-case-alias"
    analysis_dir.mkdir()
    analysis_input = analysis_dir / "Analysis.JSON"
    shutil.copyfile(fixture_dir / "linear.jsonl", analysis_input)
    analysis_original = analysis_input.read_bytes()

    # Act
    validate_result = cli(
        "validate",
        validate_input,
        "--format",
        "jsonl",
        "--normalized-out",
        validate_alias,
        "--force",
    )
    analysis_result = cli(
        "analyze",
        analysis_input,
        "--format",
        "jsonl",
        "--output-dir",
        analysis_dir,
        "--force",
    )

    # Assert
    validate_result.assert_exit(4)
    analysis_result.assert_exit(4)
    assert_no_traceback(validate_result)
    assert_no_traceback(analysis_result)
    assert validate_input.read_bytes() == validate_original
    assert analysis_input.read_bytes() == analysis_original


def test_decode_and_invalid_unicode_failures_use_validation_exit_code(
    cli: Callable[..., CommandResult], tmp_path: Path
) -> None:
    # Arrange
    invalid_utf8 = tmp_path / "invalid-utf8.jsonl"
    invalid_utf8.write_bytes(b"\xff\xfe\x00")
    invalid_component = tmp_path / "invalid-component.jsonl"
    record = {
        "schema_version": "1.0",
        "trace_id": "unicode-control",
        "step_id": "step-1",
        "timestamp": "2026-01-01T00:00:00Z",
        "operation_type": "request",
        "component": "bad\x01label",
        "duration_ms": 1,
        "status": "ok",
        "outcome": "success",
    }
    invalid_component.write_text(f"{json.dumps(record)}\n", encoding="utf-8")

    # Act
    decode_result = cli("validate", invalid_utf8)
    unicode_result = cli("analyze", invalid_component, "--output-dir", tmp_path / "report")

    # Assert
    decode_result.assert_exit(2)
    unicode_result.assert_exit(2)
    assert "utf-8" in decode_result.stderr.lower()
    assert "component" in unicode_result.stderr.lower()
    assert_no_traceback(decode_result)
    assert_no_traceback(unicode_result)
    assert not (tmp_path / "report").exists()
