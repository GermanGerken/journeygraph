"""Integration tests: packaged vendor presets on synthetic, documentation-shaped fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from journeygraph.api import load_preset, validate_file
from journeygraph.exceptions import ValidationError

FIXTURES = Path(__file__).resolve().parents[2] / "tests_functional" / "fixtures"


def _events(name: str, preset: str) -> dict[str, dict[str, object]]:
    dataset = validate_file(FIXTURES / name, mapping=load_preset(preset))
    return {event.step_id: event.to_dict() for event in dataset.events}


def test_langfuse_observations_map_to_canonical_events() -> None:
    # Act
    events = _events("langfuse_observations.jsonl", "langfuse-observations")

    # Assert
    root = events["lf-obs-1-1"]
    assert root["trace_id"] == "lf-trace-1"
    assert "parent_step_id" not in root
    assert root["timestamp"] == "2026-10-01T09:00:00.000000Z"
    assert root["duration_ms"] == 1500
    assert root["operation_type"] == "span"
    generation = events["lf-obs-1-3"]
    assert generation["parent_step_id"] == "lf-obs-1-1"
    assert (generation["operation_type"], generation["component"]) == ("llm", "answer")
    assert (generation["input_tokens"], generation["output_tokens"]) == (410, 95)
    assert generation["cost_usd"] == 0.0021
    assert generation["metadata"] == {"environment": "production", "model": "synthetic-model"}
    assert events["lf-obs-2-2"]["status"] == "error"
    assert events["lf-obs-2-3"]["status"] == "ok"  # WARNING
    assert events["lf-obs-3-2"]["operation_type"] == "internal"  # EVENT
    assert events["lf-obs-3-2"]["duration_ms"] == 0
    serialized = json.dumps(list(events.values()))
    for forbidden in ("synthetic prompt text", "synthetic-user", "synthetic-session", "note"):
        assert forbidden not in serialized


def test_phoenix_spans_map_to_canonical_events() -> None:
    # Act
    dataset = validate_file(FIXTURES / "phoenix_spans.jsonl", mapping=load_preset("phoenix-spans"))
    events = {event.step_id: event.to_dict() for event in dataset.events}

    # Assert
    root = events["0000000100000001"]
    assert root["trace_id"] == "00000000000000000000000000000001"
    assert "parent_step_id" not in root
    assert (root["operation_type"], root["duration_ms"]) == ("chain", 1300)
    llm = events["0000000100000003"]
    assert (llm["input_tokens"], llm["output_tokens"]) == (300, 80)
    assert llm["metadata"] == {"model": "synthetic-model"}
    assert events["0000000200000001"]["status"] == "unset"
    assert events["0000000200000003"]["status"] == "error"
    assert events["0000000200000002"]["operation_type"] == "decision"
    assert events["0000000300000002"]["operation_type"] == "unspecified"
    assert "unknown_operation_type" in {warning.code for warning in dataset.warnings}
    assert "synthetic prompt text" not in json.dumps(list(events.values()))


def test_langfuse_observation_without_end_time_is_a_located_error(tmp_path: Path) -> None:
    # Arrange
    rows = (FIXTURES / "langfuse_observations.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["end_time"] = None
    path = tmp_path / "observations.jsonl"
    path.write_text("\n".join([json.dumps(first), *rows[1:]]) + "\n", encoding="utf-8")

    # Act / Assert
    with pytest.raises(ValidationError) as caught:
        validate_file(path, mapping=load_preset("langfuse-observations"))
    issue = caught.value.issues[0]
    assert issue.location == "line 1.duration_ms"
    assert "start_time / end_time" in issue.message


def test_langsmith_runs_map_to_canonical_events() -> None:
    # Act
    dataset = validate_file(
        FIXTURES / "langsmith_runs.jsonl", mapping=load_preset("langsmith-runs")
    )
    events = {event.step_id: event.to_dict() for event in dataset.events}

    # Assert
    root = events["0193a1b2-0000-7000-8000-000000000001"]
    assert "parent_step_id" not in root
    assert (root["operation_type"], root["duration_ms"]) == ("chain", 1800)
    parser = events["0193a1b2-0001-7000-8000-000000000004"]
    assert parser["parent_step_id"] == "0193a1b2-0001-7000-8000-000000000003"
    assert parser["operation_type"] == "parser"
    llm = events["0193a1b2-0001-7000-8000-000000000003"]
    assert (llm["input_tokens"], llm["output_tokens"], llm["cost_usd"]) == (420, 90, 0.0031)
    assert events["0193a1b2-0002-7000-8000-000000000002"]["status"] == "error"
    assert events["0193a1b2-0000-7000-8000-000000000003"]["status"] == "unset"
    assert events["0193a1b2-0003-7000-8000-000000000002"]["operation_type"] == "prompt"
    serialized = json.dumps(list(events.values()))
    for forbidden in ("synthetic prompt text", "someone@example.invalid", "synthetic-thread"):
        assert forbidden not in serialized


def test_unfinished_langsmith_run_is_a_located_error(tmp_path: Path) -> None:
    rows = (FIXTURES / "langsmith_runs.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["end_time"] = None
    path = tmp_path / "runs.jsonl"
    path.write_text("\n".join([json.dumps(first), *rows[1:]]) + "\n", encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        validate_file(path, mapping=load_preset("langsmith-runs"))
    assert caught.value.issues[0].location == "line 1.duration_ms"
