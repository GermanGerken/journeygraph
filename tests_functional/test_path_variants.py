"""Black-box acceptance tests for path variants, recurring sequences, and trace filters."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests_functional.helpers import (
    CommandResult,
    assert_analysis_artifacts,
    assert_no_traceback,
    inspect_static_html,
    read_jsonl,
)

FIXTURE = "path_variants.jsonl"


def _variant_text(variant: dict[str, object]) -> str:
    parts = []
    for step in variant["steps"]:  # type: ignore[attr-defined]
        text = " → ".join(step["labels"])
        if step["repeated"]:
            text = f"({text})+" if len(step["labels"]) > 1 else f"{text}+"
        parts.append(text)
    return " → ".join(parts)


def test_variants_group_unique_paths_and_sequences_explain_order(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange: 6 successful search-retry traces, 4 failing search/validation loops,
    # 4 successful retrieval-then-model traces, and 4 failing model-then-retrieval traces.
    output_dir = tmp_path / "report"

    # Act
    result = cli("analyze", fixture_dir / FIXTURE, "--output-dir", output_dir)

    # Assert
    result.assert_exit(0)
    analysis = assert_analysis_artifacts(output_dir)
    assert len(analysis["paths"]) == 12
    variants = {_variant_text(item): item for item in analysis["path_variants"]}
    assert {name: (item["trace_count"], item["path_count"]) for name, item in variants.items()} == {
        "request:user → tool:search+ → model:llm": (6, 6),
        "request:user → (tool:search → validation:check)+ → model:llm": (4, 4),
        "request:user → retrieval:docs → model:llm": (4, 1),
        "request:user → model:llm → retrieval:docs": (4, 1),
    }

    items = analysis["findings"]["items"]
    assert [(item["kind"], item["label"]) for item in items] == [
        ("outcome_association", "validation:check"),
        ("sequence_association", "request:user → model:llm"),
        ("sequence_association", "tool:search → model:llm"),
        ("sequence_association", "request:user → retrieval:docs"),
        ("duration_concentration", "model:llm"),
        ("retry_prevalence", "tool:search"),
    ]
    assert items[2]["value"] == 1.0
    assert items[2]["baseline"] == pytest.approx(4 / 12)
    labels = {tuple(item["labels"]) for item in analysis["sequence_patterns"]}
    assert ("retrieval:docs", "model:llm") in labels
    assert ("tool:search", "tool:search") not in labels
    assert analysis["filters"] == {
        "outcomes": None,
        "since": None,
        "until": None,
        "input_trace_count": 18,
        "retained_trace_count": 18,
    }

    html = inspect_static_html(output_dir / "report.html")
    assert html.text.index("Path variants") < html.text.index("Chronological paths")
    assert "request:user → (tool:search → validation:check)+ → model:llm" in html.text
    assert "Recurring sequences" in html.text


def test_outcome_and_time_filters_restrict_every_artifact(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange: trace start times are 09:00, 09:01, ... in fixture order (18 traces).
    output_dir = tmp_path / "filtered"

    # Act
    result = cli(
        "analyze",
        fixture_dir / FIXTURE,
        "--output-dir",
        output_dir,
        "--outcome",
        "failure",
        "--since",
        "2026-10-01T11:08:00+02:00",
        "--until",
        "2026-10-01T09:16:00Z",
    )

    # Assert: failures are loop-2..5 (09:06-09:09) and late-0..3 (09:14-09:17).
    result.assert_exit(0)
    analysis = assert_analysis_artifacts(output_dir)
    assert analysis["totals"]["traces"] == 4
    assert analysis["filters"] == {
        "outcomes": ["failure"],
        "since": "2026-10-01T09:08:00.000000Z",
        "until": "2026-10-01T09:16:00.000000Z",
        "input_trace_count": 18,
        "retained_trace_count": 4,
    }
    normalized = read_jsonl(output_dir / "normalized.jsonl")
    assert sorted({record["trace_id"] for record in normalized}) == [
        "late-0",
        "late-1",
        "loop-4",
        "loop-5",
    ]
    html = inspect_static_html(output_dir / "report.html")
    assert "4 of 18 accepted trace(s) analyzed" in html.text


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("--outcome", "victory"), "--outcome"),
        (("--since", "2026-10-01T09:00:00"), "UTC offset"),
        (("--until", "soon"), "ISO 8601"),
        (("--outcome", "handoff"), "filter_excluded_all_traces"),
        (
            ("--since", "2026-10-02T00:00:00Z", "--until", "2026-10-01T00:00:00Z"),
            "empty_time_window",
        ),
    ],
)
def test_invalid_or_empty_filters_fail_without_artifacts(
    cli: Callable[..., CommandResult],
    fixture_dir: Path,
    tmp_path: Path,
    arguments: tuple[str, ...],
    message: str,
) -> None:
    # Act
    result = cli("analyze", fixture_dir / FIXTURE, "--output-dir", tmp_path / "out", *arguments)

    # Assert
    result.assert_exit(2)
    assert message in result.stderr
    assert_no_traceback(result)
    assert not (tmp_path / "out").exists()
