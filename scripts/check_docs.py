"""Check durable documentation, local links, schemas, and the packaged demo."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import SchemaError  # type: ignore[import-untyped]
from jsonschema.exceptions import (
    ValidationError as JsonSchemaValidationError,
)

from journeygraph.api import analyze_file

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
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
    "docs/releasing.md",
    "docs/exec-plans/journeygraph-mvp.md",
    "src/journeygraph/schemas/event-v1.schema.json",
    "src/journeygraph/schemas/analysis-v1.schema.json",
    "src/journeygraph/data/demo.jsonl",
)
LOCAL_LINK = re.compile(r"\[[^]]+\]\((?!https?://|mailto:|#)(?P<target>[^)]+)\)")


def _error(message: str) -> None:
    print(f"documentation error: {message}", file=sys.stderr)


def _check_required_files() -> list[str]:
    return [relative for relative in REQUIRED_FILES if not (ROOT / relative).is_file()]


def _check_markdown_links() -> list[str]:
    failures: list[str] = []
    for markdown in sorted(ROOT.rglob("*.md")):
        if any(part.startswith(".") and part not in {".github"} for part in markdown.parts):
            continue
        text = markdown.read_text(encoding="utf-8")
        for match in LOCAL_LINK.finditer(text):
            raw_target = match.group("target").strip("<>").split("#", maxsplit=1)[0]
            if not raw_target:
                continue
            target = (markdown.parent / raw_target).resolve()
            if not target.exists():
                failures.append(f"{markdown.relative_to(ROOT)} -> {raw_target}")
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


def _check_version_and_readme() -> list[str]:
    failures: list[str] = []
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version_source = (ROOT / "src/journeygraph/version.py").read_text(encoding="utf-8")
    if f'__version__ = "{project["version"]}"' not in version_source:
        failures.append("pyproject.toml and journeygraph.version disagree")
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
    failures.extend(_check_version_and_readme())
    failures.extend(_check_demo())
    if failures:
        for failure in failures:
            _error(failure)
        return 1
    print("documentation checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
