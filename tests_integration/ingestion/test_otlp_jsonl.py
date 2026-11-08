"""Collector file-exporter JSON Lines decode to the same records as one OTLP/JSON request."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from journeygraph.api import analyze_file
from journeygraph.exceptions import FormatError

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    ROOT / "test-data" / "fixtures" / "integration" / "openinference-scenarios.otlp.json",
    ROOT / "test-data" / "fixtures" / "integration" / "otel-demo-3.0.0.otlp.json",
    ROOT / "tests_integration" / "fixtures" / "otlp" / "golden" / "edge-cases.otlp.json",
]


def _split_per_span(source: Path, target: Path) -> int:
    """Write one ExportTraceServiceRequest per span, as a Collector batch of size one would."""

    payload = json.loads(source.read_text(encoding="utf-8"))
    lines: list[str] = []
    for resource_span in payload["resourceSpans"]:
        resource = {key: value for key, value in resource_span.items() if key != "scopeSpans"}
        for scope_span in resource_span["scopeSpans"]:
            scope = {key: value for key, value in scope_span.items() if key != "spans"}
            for span in scope_span["spans"]:
                request = {
                    "resourceSpans": [{**resource, "scopeSpans": [{**scope, "spans": [span]}]}]
                }
                lines.append(json.dumps(request, separators=(",", ":")))
    target.write_text("\n".join(lines) + "\n\n", encoding="utf-8")
    return len(lines)


def _meaning(report: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in report.items() if key != "warnings"}


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
def test_split_collector_export_matches_single_request(source: Path, tmp_path: Path) -> None:
    # Arrange
    split = tmp_path / "export.jsonl"
    line_count = _split_per_span(source, split)

    # Act
    single = analyze_file(source, input_format="otlp-json")
    lines = analyze_file(split, input_format="otlp-jsonl")

    # Assert
    assert line_count > 1
    assert _meaning(dict(lines.report)) == _meaning(dict(single.report))
    assert [event.to_dict() for event in lines.dataset.events] == [
        event.to_dict() for event in single.dataset.events
    ]
    codes = {getattr(issue, "code", None) for issue in lines.dataset.warnings}
    assert "otlp_chronological_adjacency" in codes


@pytest.mark.parametrize(
    ("content", "code"),
    [
        ('{"resourceSpans": []}\n{not json}\n', "malformed_otlp_jsonl"),
        ("\n\n", "empty_otlp_jsonl"),
        ("[1, 2]\n", "line 1"),
        ('{"resourceSpans": 5}\n', "line 1.resourceSpans"),
    ],
)
def test_malformed_collector_lines_are_format_errors(
    content: str, code: str, tmp_path: Path
) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(FormatError, match=code.replace(".", r"\.")):
        analyze_file(path, input_format="otlp-jsonl")


def test_single_request_errors_keep_their_root_location(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "bad.json"
    path.write_text('{"resourceSpans": 5}', encoding="utf-8")

    # Act / Assert
    with pytest.raises(FormatError, match=r"root\.resourceSpans"):
        analyze_file(path, input_format="otlp-json")
