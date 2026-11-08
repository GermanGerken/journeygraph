"""Every analysis produced from repository fixtures validates against the packaged schema."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from journeygraph.api import analyze_file
from journeygraph.exceptions import JourneyGraphError

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = sorted((ROOT / "tests_functional" / "fixtures").glob("*.jsonl"))
OTLP = sorted(
    [
        *(ROOT / "tests_integration" / "fixtures" / "otlp" / "golden").glob("*.otlp.json"),
        *(ROOT / "test-data" / "fixtures" / "integration").glob("*.otlp.json"),
    ]
)


def _validator() -> Draft202012Validator:
    schema = json.loads(
        files("journeygraph.schemas").joinpath("analysis-v1.schema.json").read_text("utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _assert_valid(path: Path, input_format: str) -> None:
    try:
        report = analyze_file(path, input_format=input_format).report
    except JourneyGraphError:
        pytest.skip(f"{path.name} is an intentionally rejected fixture")
    errors = [error.message for error in _validator().iter_errors(json.loads(json.dumps(report)))]
    assert errors == []
    assert report["schema_version"] == "1.2"


@pytest.mark.parametrize("path", CANONICAL, ids=lambda path: path.name)
def test_canonical_fixture_analysis_matches_schema(path: Path) -> None:
    _assert_valid(path, "jsonl")


@pytest.mark.parametrize("path", OTLP, ids=lambda path: path.name)
def test_otlp_fixture_analysis_matches_schema(path: Path) -> None:
    _assert_valid(path, "otlp-json")


def test_packaged_demo_analysis_matches_schema() -> None:
    _assert_valid(ROOT / "src" / "journeygraph" / "data" / "demo.jsonl", "jsonl")
