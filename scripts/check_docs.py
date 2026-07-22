"""Check durable documentation, local links, schemas, and the packaged demo."""

from __future__ import annotations

import json
import re

# The repository check invokes Git with a fixed argument vector and no shell.
import subprocess  # nosec B404
import sys
import tomllib
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from jsonschema.exceptions import (
    ValidationError as JsonSchemaValidationError,
)

from journeygraph.api import analyze_file

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    ".github/workflows/release.yml",
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "docs/architecture.md",
    "docs/schema.md",
    "docs/privacy.md",
    "docs/testing.md",
    "docs/cli.md",
    "docs/real-trace-discovery.md",
    "docs/releasing.md",
    "docs/exec-plans/journeygraph-mvp.md",
    "docs/exec-plans/real-trace-discovery.md",
    "docs/research/schemas/real-trace-evidence-v1.schema.json",
    "docs/research/examples/real-trace-evidence.synthetic.json",
    "docs/exec-plans/pypi-trusted-publishing.md",
    "src/journeygraph/schemas/event-v1.schema.json",
    "src/journeygraph/schemas/analysis-v1.schema.json",
    "src/journeygraph/data/demo.jsonl",
)
LOCAL_LINK = re.compile(r"\[[^]]+\]\((?!https?://|mailto:|#)(?P<target>[^)]+)\)")
PUBLIC_ISSUE_URL = re.compile(r"https://github\.com/GermanGerken/journeygraph/issues/[1-9][0-9]*")
EXTERNAL_ACTION = re.compile(r"^\s*uses:\s*(?P<action>[^@\s]+)@(?P<ref>[^\s#]+)", re.MULTILINE)


def _error(message: str) -> None:
    print(f"documentation error: {message}", file=sys.stderr)


def _check_required_files() -> list[str]:
    return [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]


def _check_markdown_links() -> list[str]:
    failures: list[str] = []
    for markdown in sorted(ROOT.rglob("*.md")):
        relative = markdown.relative_to(ROOT)
        if relative.parts[0] == "mutants":
            continue
        if any(part.startswith(".") and part not in {".github"} for part in markdown.parts):
            continue
        text = markdown.read_text(encoding="utf-8")
        for match in LOCAL_LINK.finditer(text):
            raw_target = match.group("target").strip("<>").split("#", maxsplit=1)[0]
            if not raw_target:
                continue
            target = (markdown.parent / raw_target).resolve()
            if not target.exists():
                failures.append(f"{relative} -> {raw_target}")
    return failures


def _check_json_contracts() -> list[str]:
    failures: list[str] = []
    schemas: dict[str, dict[str, object]] = {}
    for relative in (
        "src/journeygraph/schemas/event-v1.schema.json",
        "src/journeygraph/schemas/analysis-v1.schema.json",
    ):
        try:
            value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"{relative}: {error}")
            continue
        if not isinstance(value, dict) or "$schema" not in value or "$id" not in value:
            failures.append(f"{relative}: missing $schema or $id")
            continue
        schemas[relative] = value

    event_schema = schemas.get("src/journeygraph/schemas/event-v1.schema.json", {})
    event_description = str(event_schema.get("description", "")).lower()
    if (
        event_schema.get("additionalProperties") is not False
        or "normalized" not in event_description
    ):
        failures.append("event-v1 schema must identify strict normalized output")

    analysis_schema = schemas.get("src/journeygraph/schemas/analysis-v1.schema.json", {})
    expected_sections = {
        "schema_version",
        "tool_version",
        "config",
        "totals",
        "outcomes",
        "nodes",
        "transitions",
        "entries",
        "terminals",
        "paths",
        "retries",
        "loops",
        "failure_points",
        "dropoff_points",
        "path_comparison",
        "cohorts",
        "metrics",
        "warnings",
    }
    analysis_required = analysis_schema.get("required", [])
    if not isinstance(analysis_required, list) or set(analysis_required) != expected_sections:
        failures.append("analysis-v1 schema required sections drifted from the public contract")
    properties = analysis_schema.get("properties", {})
    totals = properties.get("totals", {}) if isinstance(properties, dict) else {}
    expected_totals = {
        "input_records",
        "events",
        "traces",
        "nodes",
        "transitions",
        "unique_transitions",
        "paths",
        "warnings",
    }
    totals_required = totals.get("required", []) if isinstance(totals, dict) else []
    if not isinstance(totals_required, list) or set(totals_required) != expected_totals:
        failures.append("analysis-v1 totals must require every emitted counter")

    if event_schema and analysis_schema:
        try:
            Draft202012Validator.check_schema(event_schema)
            Draft202012Validator.check_schema(analysis_schema)
            demo_analysis = analyze_file(
                ROOT / "src/journeygraph/data/demo.jsonl",
                input_format="jsonl",
            )
            event_validator = Draft202012Validator(event_schema)
            for event in demo_analysis.dataset.events:
                event_validator.validate(event.to_dict())
            Draft202012Validator(analysis_schema).validate(demo_analysis.report)
        except (SchemaError, JsonSchemaValidationError) as error:
            failures.append(f"schema validation failed: {error.message}")
    return failures


def _as_object_list(value: object, *, label: str, failures: list[str]) -> list[dict[str, object]]:
    if not isinstance(value, list):
        failures.append(f"research evidence {label} must be an array")
        return []
    objects: list[dict[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            failures.append(f"research evidence {label}[{index}] must be an object")
            continue
        objects.append(cast(dict[str, object], item))
    return objects


def _unique_ids(
    objects: list[dict[str, object]], *, key: str, label: str, failures: list[str]
) -> set[str]:
    values: list[str] = []
    for index, item in enumerate(objects):
        value = item.get(key)
        if not isinstance(value, str):
            failures.append(f"research evidence {label}[{index}].{key} must be a string")
            continue
        values.append(value)
    if len(values) != len(set(values)):
        failures.append(f"research evidence contains duplicate {label} {key} values")
    return set(values)


def _reference_list(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def _contains_forbidden_local_reference(value: object, *, field_name: str | None = None) -> bool:
    """Reject path separators except in the canonical public issue URL field."""

    if isinstance(value, str):
        if field_name == "public_issue_url" and PUBLIC_ISSUE_URL.fullmatch(value):
            return False
        return "/" in value or "\\" in value
    if isinstance(value, list):
        return any(_contains_forbidden_local_reference(item) for item in value)
    if isinstance(value, dict):
        return any(
            _contains_forbidden_local_reference(item, field_name=key) for key, item in value.items()
        )
    return False


def _public_evidence_example_paths(examples_root: Path, failures: list[str]) -> list[Path]:
    """Return the allowlisted public evidence examples without exposing rejected names."""

    if examples_root.is_symlink():
        failures.append("docs/research/examples cannot be a symbolic link")
        return []
    try:
        entries = sorted(examples_root.iterdir())
    except OSError as error:
        failures.append(f"cannot inspect public research evidence examples: {error}")
        return []
    example_paths: list[Path] = []
    for entry in entries:
        if entry.is_symlink() or not entry.is_file() or entry.suffix != ".json":
            failures.append(
                "docs/research/examples may contain only regular top-level JSON files; "
                "rejected path omitted"
            )
            continue
        example_paths.append(entry)
    if not example_paths:
        failures.append("research evidence requires at least one public JSON example")
    return example_paths


def _check_research_references(document: dict[str, object]) -> list[str]:
    failures: list[str] = []
    datasets = _as_object_list(document.get("datasets"), label="datasets", failures=failures)
    runs = _as_object_list(document.get("runs"), label="runs", failures=failures)
    gaps = _as_object_list(document.get("gaps"), label="gaps", failures=failures)
    dataset_ids = _unique_ids(datasets, key="dataset_id", label="datasets", failures=failures)
    run_ids = _unique_ids(runs, key="run_id", label="runs", failures=failures)
    gap_ids = _unique_ids(gaps, key="gap_id", label="gaps", failures=failures)
    runs_by_id = {run_id: run for run in runs if isinstance((run_id := run.get("run_id")), str)}
    gaps_by_id = {gap_id: gap for gap in gaps if isinstance((gap_id := gap.get("gap_id")), str)}
    run_positions = {
        run_id: index
        for index, run in enumerate(runs)
        if isinstance((run_id := run.get("run_id")), str)
    }

    for index, run in enumerate(runs):
        run_id = run.get("run_id", "unknown")
        if run.get("dataset_id") not in dataset_ids:
            failures.append(f"research evidence run {run_id} references an unknown dataset")
        command = run.get("command")
        if isinstance(command, dict) and command.get("input_reference") != run.get("dataset_id"):
            failures.append(f"research evidence run {run_id} input reference must match dataset")
        if not _reference_list(run.get("mapping_gap_ids")).issubset(gap_ids):
            failures.append(f"research evidence run {run_id} references an unknown gap")
        supersedes = run.get("supersedes_run_id")
        if supersedes is not None and supersedes not in run_ids:
            failures.append(f"research evidence run {run_id} supersedes an unknown run")
        elif isinstance(supersedes, str) and run_positions.get(supersedes, index) >= index:
            failures.append(f"research evidence run {run_id} must supersede an earlier run")
        elif isinstance(supersedes, str):
            superseded_run = runs_by_id.get(supersedes)
            if superseded_run and superseded_run.get("dataset_id") != run.get("dataset_id"):
                failures.append(
                    f"research evidence run {run_id} must supersede a run from the same dataset"
                )

        if isinstance(run_id, str):
            for gap_id in _reference_list(run.get("mapping_gap_ids")):
                gap = gaps_by_id.get(gap_id)
                if gap is None:
                    continue
                if run_id not in _reference_list(gap.get("run_ids")):
                    failures.append(
                        f"research evidence run {run_id} and gap {gap_id} must reference each other"
                    )
                if run.get("dataset_id") not in _reference_list(gap.get("dataset_ids")):
                    failures.append(
                        f"research evidence gap {gap_id} must reference the run dataset"
                    )

    for gap in gaps:
        gap_id = gap.get("gap_id", "unknown")
        if not _reference_list(gap.get("dataset_ids")).issubset(dataset_ids):
            failures.append(f"research evidence gap {gap_id} references an unknown dataset")
        if not _reference_list(gap.get("run_ids")).issubset(run_ids):
            failures.append(f"research evidence gap {gap_id} references an unknown run")
        if isinstance(gap_id, str):
            linked_dataset_ids = {
                dataset_id
                for run_id in _reference_list(gap.get("run_ids"))
                if (referenced_run := runs_by_id.get(run_id)) is not None
                and isinstance((dataset_id := referenced_run.get("dataset_id")), str)
            }
            if _reference_list(gap.get("dataset_ids")) != linked_dataset_ids:
                failures.append(
                    f"research evidence gap {gap_id} dataset references must exactly match its runs"
                )
            for run_id in _reference_list(gap.get("run_ids")):
                referenced_run = runs_by_id.get(run_id)
                if referenced_run is None:
                    continue
                if gap_id not in _reference_list(referenced_run.get("mapping_gap_ids")):
                    failures.append(
                        f"research evidence gap {gap_id} and run {run_id} must reference each other"
                    )
                if referenced_run.get("dataset_id") not in _reference_list(gap.get("dataset_ids")):
                    failures.append(
                        f"research evidence gap {gap_id} must reference every run dataset"
                    )

    study = document.get("study")
    if isinstance(study, dict):
        for hypothesis_name in ("primary_persona", "target_job"):
            hypothesis = study.get(hypothesis_name)
            if isinstance(hypothesis, dict) and not _reference_list(
                hypothesis.get("evidence_run_ids")
            ).issubset(run_ids):
                failures.append(f"research evidence {hypothesis_name} references an unknown run")
    return failures


def _check_research_evidence() -> list[str]:
    failures: list[str] = []
    schema_path = ROOT / "docs/research/schemas/real-trace-evidence-v1.schema.json"
    try:
        schema_value: object = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"research evidence schema: {error}"]
    if not isinstance(schema_value, dict):
        return ["research evidence schema must be an object"]
    schema = cast(dict[str, object], schema_value)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        return [f"research evidence schema is invalid: {error.message}"]

    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    example_paths = _public_evidence_example_paths(ROOT / "docs/research/examples", failures)
    for example_path in example_paths:
        relative = example_path.relative_to(ROOT)
        try:
            value: object = json.loads(example_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            failures.append(f"{relative}: {error}")
            continue
        if not isinstance(value, dict):
            failures.append(f"{relative}: evidence example must be an object")
            continue
        document = cast(dict[str, object], value)
        if _contains_forbidden_local_reference(document):
            failures.append(f"{relative}: evidence metadata contains a local path")
        validation_errors = sorted(
            validator.iter_errors(document),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        failures.extend(
            f"{relative}: schema validation failed at "
            f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in validation_errors
        )
        record_class = document.get("record_class")
        if record_class not in {"synthetic_example", "public_summary"}:
            failures.append(f"{relative}: committed examples cannot contain private evidence")
        failures.extend(
            f"{relative}: {failure}" for failure in _check_research_references(document)
        )
    return failures


def _check_private_data_boundary() -> list[str]:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    failures = [] if "data/private/" in gitignore else [".gitignore must exclude data/private/"]
    try:
        # Fixed Git argv; output is counted but never printed because a private filename can leak.
        completed = subprocess.run(  # nosec B603 B607
            ["git", "ls-files", "-z", "--", "data/private"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        failures.append(f"cannot verify tracked private-data boundary: {error}")
        return failures
    if completed.returncode != 0:
        failures.append("git ls-files failed while checking the private-data boundary")
    elif any(completed.stdout.split(b"\0")):
        failures.append("tracked files exist under data/private; filenames intentionally omitted")

    try:
        # Evidence JSON is valid only in the reviewed public examples directory.
        tracked_json = subprocess.run(  # nosec B603 B607
            ["git", "ls-files", "-z", "--", "*.json"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        failures.append(f"cannot verify tracked evidence locations: {error}")
        return failures
    if tracked_json.returncode != 0:
        failures.append("git ls-files failed while checking tracked evidence locations")
        return failures
    for raw_path in tracked_json.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = ROOT / raw_path.decode("utf-8", errors="surrogateescape")
        try:
            value: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(value, dict)
            and value.get("record_class")
            in {"synthetic_example", "private_evidence", "public_summary"}
            and path.parent != ROOT / "docs/research/examples"
        ):
            failures.append(
                "tracked research evidence exists outside docs/research/examples; path omitted"
            )
            break
        if (
            path.is_symlink()
            and isinstance(value, dict)
            and value.get("record_class")
            in {"synthetic_example", "private_evidence", "public_summary"}
        ):
            failures.append("tracked research evidence cannot be a symbolic link; path omitted")
            break
    return failures


def _check_version_and_readme() -> list[str]:
    failures: list[str] = []
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version_source = (ROOT / "src/journeygraph/version.py").read_text(encoding="utf-8")
    if f'__version__ = "{project["version"]}"' not in version_source:
        failures.append("pyproject.toml and journeygraph.version disagree")
    urls = project.get("urls", {})
    if not isinstance(urls, dict) or not {"Changelog", "Security"}.issubset(urls):
        failures.append("project URLs must include Changelog and Security")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required_phrases = (
        "JourneyGraph does not collect traces.",
        "journeygraph demo",
        "journeygraph analyze",
        "Local-first",
        "Apache License 2.0",
    )
    failures.extend(
        f"README.md is missing required phrase: {phrase}"
        for phrase in required_phrases
        if phrase not in readme
    )
    return failures


def _check_release_workflow() -> list[str]:
    failures: list[str] = []
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    required_fragments = (
        "types: [published]",
        "permissions: {}",
        "name: pypi",
        "id-token: write",
        "skip-existing: false",
        "scripts/verify_distribution.py",
        "scripts/verify_published.py",
    )
    failures.extend(
        f"release workflow is missing required contract: {fragment}"
        for fragment in required_fragments
        if fragment not in workflow
    )
    prohibited_fragments = ("workflow_dispatch:", "pull_request_target:", "password:")
    failures.extend(
        f"release workflow contains prohibited contract: {fragment}"
        for fragment in prohibited_fragments
        if fragment in workflow
    )
    if workflow.count("id-token: write") != 1:
        failures.append("release workflow must grant id-token: write to exactly one job")
    if workflow.count("ref: ${{ github.sha }}") != 2:
        failures.append("release workflow must bind both checkouts to the release event commit")
    failures.extend(
        (
            "release workflow action must use a full immutable commit SHA: "
            f"{match.group('action')}@{match.group('ref')}"
        )
        for match in EXTERNAL_ACTION.finditer(workflow)
        if re.fullmatch(r"[0-9a-f]{40}", match.group("ref")) is None
    )
    return failures


def _check_ci_workflow() -> list[str]:
    failures: list[str] = []
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    required_fragments = (
        "name: Windows package and CLI (Python 3.12)",
        "runs-on: windows-latest",
        'python-version: "3.12"',
        "python -m build",
        "python -m twine check --strict dist/*",
        "python scripts/verify_wheel.py",
    )
    failures.extend(
        f"CI workflow is missing the Windows package contract: {fragment}"
        for fragment in required_fragments
        if fragment not in workflow
    )
    return failures


def _check_demo() -> list[str]:
    failures: list[str] = []
    demo = ROOT / "src/journeygraph/data/demo.jsonl"
    records = []
    for line_number, line in enumerate(demo.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            failures.append(f"demo.jsonl:{line_number}: {error}")
            continue
        if not isinstance(value, dict) or value.get("schema_version") != "1.0":
            failures.append(f"demo.jsonl:{line_number}: not a journeygraph.event/v1 object")
        records.append(value)
    if len(records) < 10:
        failures.append("demo.jsonl must contain a useful multi-trace scenario")
    return failures


def main() -> int:
    """Run all deterministic offline documentation checks."""

    failures: list[str] = []
    failures.extend(f"missing required file: {path}" for path in _check_required_files())
    failures.extend(f"broken local link: {link}" for link in _check_markdown_links())
    failures.extend(_check_json_contracts())
    failures.extend(_check_research_evidence())
    failures.extend(_check_private_data_boundary())
    failures.extend(_check_version_and_readme())
    failures.extend(_check_release_workflow())
    failures.extend(_check_ci_workflow())
    failures.extend(_check_demo())
    if failures:
        for failure in failures:
            _error(failure)
        return 1
    print("documentation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
