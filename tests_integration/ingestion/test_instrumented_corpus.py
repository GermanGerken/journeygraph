from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from journeygraph.api import analyze_file, validate_file

ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_FIXTURES = ROOT / "test-data" / "fixtures" / "integration"
GOLDEN_FIXTURE = (
    ROOT / "tests_integration" / "fixtures" / "otlp" / "golden" / "edge-cases.otlp.json"
)


def _warning_codes(dataset: Any) -> list[str]:
    return [warning.code for warning in dataset.warnings]


def _outcome_counts(report: dict[str, Any]) -> dict[str, int]:
    outcomes = cast(dict[str, Any], report["outcomes"])
    return cast(dict[str, int], outcomes["counts"])


def test_actual_openinference_export_preserves_scenarios_and_safe_semantics() -> None:
    # Arrange
    fixture = INTEGRATION_FIXTURES / "openinference-scenarios.otlp.json"

    # Act
    analysis = analyze_file(fixture, input_format="otlp-json")

    # Assert
    assert analysis.dataset.input_record_count == 17
    assert len(analysis.dataset.events) == 17
    assert len(analysis.dataset.traces) == 7
    assert _outcome_counts(cast(dict[str, Any], analysis.report)) == {
        "success": 4,
        "failure": 1,
        "handoff": 1,
        "dropoff": 0,
        "unknown": 1,
    }
    assert sum(event.status == "error" for event in analysis.dataset.events) == 2
    assert cast(list[dict[str, Any]], analysis.report["retries"])[0]["count"] == 1
    assert cast(list[dict[str, Any]], analysis.report["dropoff_points"]) == []
    assert "missing_outcome" in _warning_codes(analysis.dataset)

    components = {event.component for event in analysis.dataset.events}
    assert {
        "offline-model-v1",
        "catalog-lookup",
        "inventory-check",
        "policy-check",
        "unstable-service",
        "retryable-service",
        "triage-agent",
        "specialist-agent",
        "last-observed-step",
    } <= components


def test_concurrent_siblings_are_chronological_adjacency_not_parent_control_flow() -> None:
    # Arrange
    fixture = INTEGRATION_FIXTURES / "openinference-scenarios.otlp.json"

    # Act
    analysis = analyze_file(fixture, input_format="otlp-json")
    trace = next(
        item
        for item in analysis.dataset.traces
        if {event.component for event in item.events} >= {"inventory-check", "policy-check"}
    )
    inventory = next(event for event in trace.events if event.component == "inventory-check")
    policy = next(event for event in trace.events if event.component == "policy-check")
    transitions = cast(list[dict[str, Any]], analysis.report["transitions"])

    # Assert
    assert inventory.parent_step_id == policy.parent_step_id
    assert inventory.step_id != policy.parent_step_id
    assert policy.step_id != inventory.parent_step_id
    inventory_end_ns = inventory.timestamp_ns + int(inventory.duration_ms * 1_000_000)
    assert inventory.timestamp_ns < policy.timestamp_ns < inventory_end_ns
    assert any(
        transition["source_label"] == "tool:inventory-check"
        and transition["target_label"] == "tool:policy-check"
        for transition in transitions
    )
    assert "otlp_chronological_adjacency" in _warning_codes(analysis.dataset)


def test_actual_opentelemetry_demo_export_is_multiservice_errorful_and_deterministic() -> None:
    # Arrange
    fixture = INTEGRATION_FIXTURES / "otel-demo-3.0.0.otlp.json"

    # Act
    first = analyze_file(fixture, input_format="otlp-json")
    second = analyze_file(fixture, input_format="otlp-json")

    # Assert
    assert first.dataset.input_record_count == 55
    assert len(first.dataset.events) == 55
    assert len(first.dataset.traces) == 5
    assert len({event.metadata.get("service") for event in first.dataset.events}) == 9
    assert sum(event.parent_step_id is not None for event in first.dataset.events) == 50
    assert sum(event.status == "error" for event in first.dataset.events) == 2
    assert _outcome_counts(cast(dict[str, Any], first.report)) == {
        "success": 0,
        "failure": 0,
        "handoff": 0,
        "dropoff": 0,
        "unknown": 5,
    }
    assert cast(list[dict[str, Any]], first.report["dropoff_points"]) == []
    assert _warning_codes(first.dataset).count("missing_outcome") == 5
    assert _warning_codes(first.dataset).count("out_of_order_input") == 3
    assert first.report == second.report
    assert [event.to_dict() for event in first.dataset.events] == [
        event.to_dict() for event in second.dataset.events
    ]


def test_golden_fixture_covers_composite_anyvalues_duplicates_and_missing_parent() -> None:
    # Arrange
    fixture = GOLDEN_FIXTURE

    # Act
    dataset = validate_file(fixture, input_format="otlp-json")

    # Assert
    assert dataset.input_record_count == 5
    assert len(dataset.events) == 4
    assert len(dataset.traces) == 2
    assert {trace.outcome for trace in dataset.traces} == {"unknown"}
    assert sum(event.status == "error" for event in dataset.events) == 1
    assert all(set(event.metadata) <= {"service"} for event in dataset.events)
    assert {
        "duplicate_event_removed",
        "missing_outcome",
        "missing_parent",
        "otlp_chronological_adjacency",
        "out_of_order_input",
    } <= set(_warning_codes(dataset))


def test_conflicting_duplicate_otlp_span_identity_is_rejected(tmp_path: Path) -> None:
    # Arrange
    payload = cast(dict[str, Any], json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8")))
    conflicting = copy.deepcopy(payload)
    spans = conflicting["resourceSpans"][0]["scopeSpans"][0]["spans"]
    spans[3]["name"] = "conflicting-root"
    input_path = tmp_path / "conflicting-duplicate.json"
    input_path.write_text(json.dumps(conflicting), encoding="utf-8")

    # Act
    with pytest.raises(Exception) as exc_info:
        validate_file(input_path, input_format="otlp-json")

    # Assert
    assert exc_info.type.__name__ == "ValidationError"
    assert "conflicting_duplicate" in str(exc_info.value)


def test_collector_file_exporter_jsonl_is_not_claimed_as_otlp_import(tmp_path: Path) -> None:
    # Arrange
    payload = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
    input_path = tmp_path / "collector-file-export.jsonl"
    encoded = json.dumps(payload, separators=(",", ":"))
    input_path.write_text(f"{encoded}\n{encoded}\n", encoding="utf-8")

    # Act
    with pytest.raises(Exception) as exc_info:
        validate_file(input_path, input_format="otlp-json")

    # Assert
    assert exc_info.type.__name__ == "FormatError"
    assert "malformed_otlp_json" in str(exc_info.value)


def test_committed_instrumented_fixtures_have_matching_provenance() -> None:
    # Arrange
    fixtures = sorted(INTEGRATION_FIXTURES.glob("*.otlp.json"))

    # Act
    records = [
        json.loads(fixture.with_suffix(".provenance.json").read_text(encoding="utf-8"))
        for fixture in fixtures
    ]

    # Assert
    assert [record["classification"] for record in records] == [
        "instrumented-demo",
        "instrumented-demo",
    ]
    assert all("production" not in record["source"]["name"].casefold() for record in records)
