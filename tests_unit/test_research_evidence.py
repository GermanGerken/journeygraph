from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
check_docs = importlib.import_module("check_docs")
SCHEMA_PATH = ROOT / "docs/research/schemas/real-trace-evidence-v1.schema.json"
EXAMPLE_PATH = ROOT / "docs/research/examples/real-trace-evidence.synthetic.json"


def _document(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def test_markdown_link_check_ignores_generated_mutant_docs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    generated_docs = tmp_path / "mutants" / "docs"
    generated_docs.mkdir(parents=True)
    (generated_docs / "generated.md").write_text(
        "[generated workspace link](../missing.md)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)

    # Act
    failures = check_docs._check_markdown_links()

    # Assert
    assert failures == []


def test_synthetic_evidence_schema_and_references_are_valid() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    example = _document(EXAMPLE_PATH)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    schema_errors = list(validator.iter_errors(example))
    reference_errors = check_docs._check_research_references(example)

    # Assert
    assert schema_errors == []
    assert reference_errors == []


def test_public_summary_cannot_retain_exact_private_dimensions() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    example = copy.deepcopy(_document(EXAMPLE_PATH))
    example["record_class"] = "public_summary"
    example["datasets"][0]["access"]["storage_class"] = "public_summary_only"
    review = example["publication_review"]
    review["status"] = "passed"
    review["reviewed_on"] = "2026-07-21"
    review["reviewer_role"] = "publication-owner"
    review["independent_review_status"] = "passed"
    review["independent_reviewer_role"] = "independent-reviewer"
    review["independent_reviewed_on"] = "2026-07-21"
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    errors = list(validator.iter_errors(example))

    # Assert
    assert any("dimensions" in error.absolute_path for error in errors)


def test_public_summary_requires_identified_independent_review() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    example = _document(EXAMPLE_PATH)
    example["record_class"] = "public_summary"
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    errors = list(validator.iter_errors(example))

    # Assert
    assert any("independent_reviewer_role" in error.absolute_path for error in errors)
    assert any("independent_reviewed_on" in error.absolute_path for error in errors)


def test_synthetic_record_cannot_disguise_partner_provenance() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    example = _document(EXAMPLE_PATH)
    example["datasets"][0]["provenance"]["source_type"] = "partner_provided_export"
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    errors = list(validator.iter_errors(example))

    # Assert
    assert any("source_type" in error.absolute_path for error in errors)


def test_synthetic_run_cannot_validate_product_hypotheses() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    example = _document(EXAMPLE_PATH)
    persona = example["study"]["primary_persona"]
    persona["status"] = "validated"
    persona["evidence_run_ids"] = ["example-run-success"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    errors = list(validator.iter_errors(example))

    # Assert
    assert any("primary_persona" in error.absolute_path for error in errors)


def test_record_class_cannot_reuse_the_wrong_retention_status() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    synthetic = _document(EXAMPLE_PATH)
    synthetic["datasets"][0]["retention"]["status"] = "active"
    private = _document(EXAMPLE_PATH)
    private["record_class"] = "private_evidence"
    deleted = copy.deepcopy(private)
    deleted_retention = deleted["datasets"][0]["retention"]
    deleted_retention["status"] = "deleted"
    deleted_retention["raw_delete_by"] = "2026-08-21"
    deleted_retention["derived_delete_by"] = "2026-09-21"
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    synthetic_errors = list(validator.iter_errors(synthetic))
    private_errors = list(validator.iter_errors(private))
    deleted_errors = list(validator.iter_errors(deleted))

    # Assert
    assert any("status" in error.absolute_path for error in synthetic_errors)
    assert any("status" in error.absolute_path for error in private_errors)
    assert any("raw_deleted_on" in error.absolute_path for error in deleted_errors)
    assert any("derived_deleted_on" in error.absolute_path for error in deleted_errors)


def test_public_metadata_uses_opaque_references_and_versioned_field_categories() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    example = _document(EXAMPLE_PATH)
    example["datasets"][0]["provenance"]["license_terms_reference"] = (
        "Contract with Example Partner"
    )
    example["runs"][1]["dropped_fields"] = ["raw.partner.secret"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    errors = list(validator.iter_errors(example))

    # Assert
    assert any("license_terms_reference" in error.absolute_path for error in errors)
    assert any("dropped_fields" in error.absolute_path for error in errors)


def test_evidence_metadata_cannot_contain_local_filesystem_references() -> None:
    # Arrange
    local_references = [
        "/Users/example/private-study/input.jsonl",
        "/etc/journeygraph/config.json",
        "../../private/input.jsonl",
        "data/private/input.jsonl",
        r"C:\\private\\input.jsonl",
        r"\\server\share\input.jsonl",
        "file:///srv/private/input.jsonl",
        "~/private/input.jsonl",
        "customer-x/private/input.jsonl",
        "path=./private/input.jsonl",
        r"input=C:\private\input.jsonl",
        r"input=\\server\share\input.jsonl",
    ]

    # Act
    results = [
        check_docs._contains_forbidden_local_reference({"safe_rationale": reference})
        for reference in local_references
    ]

    # Assert
    assert all(results)
    assert (
        check_docs._contains_forbidden_local_reference(
            {"public_issue_url": "https://github.com/GermanGerken/journeygraph/issues/5"}
        )
        is False
    )
    assert check_docs._contains_forbidden_local_reference({"statement": "AI or agent"}) is False


def test_provenance_and_version_sources_are_cross_field_consistent() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    partner_with_synthetic_permission = _document(EXAMPLE_PATH)
    partner_provenance = partner_with_synthetic_permission["datasets"][0]["provenance"]
    partner_provenance["source_type"] = "partner_provided_export"

    public_with_private_permission = _document(EXAMPLE_PATH)
    public_provenance = public_with_private_permission["datasets"][0]["provenance"]
    public_provenance["source_type"] = "public_licensed_fixture"
    public_provenance["permission_basis"] = "data_processing_agreement"

    unknown_with_version = _document(EXAMPLE_PATH)
    unknown_with_version["datasets"][0]["producer"]["version_source"] = "unknown"

    known_without_version = _document(EXAMPLE_PATH)
    known_without_version["datasets"][0]["producer"]["exact_version"] = None
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    partner_errors = list(validator.iter_errors(partner_with_synthetic_permission))
    public_errors = list(validator.iter_errors(public_with_private_permission))
    unknown_errors = list(validator.iter_errors(unknown_with_version))
    known_errors = list(validator.iter_errors(known_without_version))

    # Assert
    assert any("permission_basis" in error.absolute_path for error in partner_errors)
    assert any("permission_basis" in error.absolute_path for error in public_errors)
    assert any("exact_version" in error.absolute_path for error in unknown_errors)
    assert any("exact_version" in error.absolute_path for error in known_errors)


def test_real_record_classes_cannot_reclassify_synthetic_evidence() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    private = _document(EXAMPLE_PATH)
    private["record_class"] = "private_evidence"
    public = _document(EXAMPLE_PATH)
    public["record_class"] = "public_summary"
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    private_errors = list(validator.iter_errors(private))
    public_errors = list(validator.iter_errors(public))

    # Assert
    assert any("source_type" in error.absolute_path for error in private_errors)
    assert any("version_source" in error.absolute_path for error in private_errors)
    assert any("source_type" in error.absolute_path for error in public_errors)
    assert any("version_source" in error.absolute_path for error in public_errors)


def test_public_example_directory_rejects_nested_and_non_json_entries(tmp_path: Path) -> None:
    # Arrange
    (tmp_path / "valid.json").write_text("{}", encoding="utf-8")
    (tmp_path / "trace.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    failures: list[str] = []

    # Act
    paths = check_docs._public_evidence_example_paths(tmp_path, failures)

    # Assert
    assert paths == [tmp_path / "valid.json"]
    assert len(failures) == 2
    assert all("rejected path omitted" in failure for failure in failures)


def test_successful_validate_run_reviews_only_its_command_output() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    example = _document(EXAMPLE_PATH)
    successful_run = example["runs"][1]
    successful_run["command"]["subcommand"] = "validate"
    successful_run["artifact_review"]["reviewed_artifacts"] = ["stdout_stderr"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    errors = list(validator.iter_errors(example))

    # Assert
    assert errors == []


def test_gap_cannot_publish_a_local_path_as_an_issue_url() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    example = _document(EXAMPLE_PATH)
    example["gaps"][0]["public_issue_url"] = "file:///Users/example/private-study"
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    errors = list(validator.iter_errors(example))

    # Assert
    assert any("public_issue_url" in error.absolute_path for error in errors)


def test_unknown_dataset_and_gap_references_are_rejected() -> None:
    # Arrange
    example = _document(EXAMPLE_PATH)
    example["runs"][0]["dataset_id"] = "example-unknown-dataset"
    example["runs"][0]["mapping_gap_ids"] = ["example-unknown-gap"]
    example["runs"][0]["supersedes_run_id"] = "example-run-success"

    # Act
    errors = check_docs._check_research_references(example)

    # Assert
    assert any("references an unknown dataset" in error for error in errors)
    assert any("input reference must match dataset" in error for error in errors)
    assert any("references an unknown gap" in error for error in errors)
    assert any("must supersede an earlier run" in error for error in errors)


def test_supersession_and_gap_links_are_semantically_consistent() -> None:
    # Arrange
    example = _document(EXAMPLE_PATH)
    second_dataset = copy.deepcopy(example["datasets"][0])
    second_dataset["dataset_id"] = "example-dataset-second"
    example["datasets"].append(second_dataset)
    successful_run = example["runs"][1]
    successful_run["dataset_id"] = "example-dataset-second"
    successful_run["command"]["input_reference"] = "example-dataset-second"
    successful_run["mapping_gap_ids"] = []

    # Act
    errors = check_docs._check_research_references(example)

    # Assert
    assert any("same dataset" in error for error in errors)
    assert any("must reference each other" in error for error in errors)
    assert any("must reference every run dataset" in error for error in errors)


def test_gap_dataset_references_exactly_match_linked_runs() -> None:
    # Arrange
    example = _document(EXAMPLE_PATH)
    second_dataset = copy.deepcopy(example["datasets"][0])
    second_dataset["dataset_id"] = "example-dataset-without-run"
    example["datasets"].append(second_dataset)
    example["gaps"][0]["dataset_ids"].append("example-dataset-without-run")

    # Act
    errors = check_docs._check_research_references(example)

    # Assert
    assert any("must exactly match its runs" in error for error in errors)


def test_evidence_backed_gap_requires_dataset_and_run_references() -> None:
    # Arrange
    schema = _document(SCHEMA_PATH)
    example = _document(EXAMPLE_PATH)
    example["gaps"][0]["dataset_ids"] = []
    example["gaps"][0]["run_ids"] = []
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # Act
    errors = list(validator.iter_errors(example))

    # Assert
    assert any("dataset_ids" in error.absolute_path for error in errors)
    assert any("run_ids" in error.absolute_path for error in errors)
