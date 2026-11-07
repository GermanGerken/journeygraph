"""Black-box acceptance tests for `journeygraph diff` and `journeygraph check`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests_functional.helpers import (
    CommandResult,
    assert_no_traceback,
    inspect_static_html,
    read_json,
)

BASELINE = "release_baseline.jsonl"
CANDIDATE = "release_candidate.jsonl"


def test_diff_reports_hand_computed_release_changes(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange: baseline 8 successes and 2 model errors; candidate adds a reranker on 5
    # successful traces, has 5 failing model errors, doubles cost, and raises p95 to 1500 ms.
    output_dir = tmp_path / "diff"

    # Act
    result = cli(
        "diff", fixture_dir / BASELINE, fixture_dir / CANDIDATE, "--output-dir", output_dir
    )

    # Assert
    result.assert_exit(0)
    assert sorted(path.name for path in output_dir.iterdir()) == ["diff.html", "diff.json"]
    diff = read_json(output_dir / "diff.json")
    assert diff["diff_schema_version"] == "1.0"
    assert [(change["kind"], change["label"]) for change in diff["changes"]] == [
        ("success_rate_change", "success among known outcomes"),
        ("category_added", "tool:rerank"),
        ("category_error_rate_change", "model:llm"),
        ("variant_share_change", "request:user → retrieval:docs → tool:rerank → model:llm"),
        ("variant_share_change", "request:user → retrieval:docs → model:llm"),
        ("cost_per_trace_change", "Mean supplied cost per trace"),
        ("duration_p95_change", "Event p95 duration (ms)"),
    ]
    success = diff["outcomes"]["known_success"]
    assert (success["baseline"], success["candidate"]) == (0.8, 0.5)
    assert success["interval"]["method"] == "newcombe"
    # With 10 traces per side the 95% interval for the -0.3 change still includes zero.
    assert success["interval"]["low"] < -0.3 < 0 < success["interval"]["high"]
    assert diff["metrics"]["mean_cost_per_trace"]["relative_delta"] == 1.0
    assert diff["metrics"]["duration_p95_ms"] == {
        "baseline": 1000.0,
        "candidate": 1500.0,
        "delta": 500.0,
        "relative_delta": 0.5,
    }
    assert "change: Success among known outcomes moved from 80% to 50%" in result.stdout

    html = inspect_static_html(output_dir / "diff.html")
    assert "Notable changes" in html.text
    assert "tool:rerank is new" in html.text


def test_diff_is_deterministic_and_protects_inputs(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Act
    cli(
        "diff", fixture_dir / BASELINE, fixture_dir / CANDIDATE, "--output-dir", tmp_path / "a"
    ).assert_exit(0)
    cli(
        "diff", fixture_dir / BASELINE, fixture_dir / CANDIDATE, "--output-dir", tmp_path / "b"
    ).assert_exit(0)
    occupied = cli(
        "diff", fixture_dir / BASELINE, fixture_dir / CANDIDATE, "--output-dir", tmp_path / "a"
    )

    # Assert
    for name in ("diff.json", "diff.html"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    occupied.assert_exit(4)
    assert_no_traceback(occupied)


def _rules(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "rules.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_check_passes_and_fails_with_documented_exit_codes(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    # Arrange
    passing = _rules(
        tmp_path, "[thresholds]\nmin_success_rate = 0.5\nmax_error_event_rate = 0.15\n"
    )
    failing = tmp_path / "failing.toml"
    failing.write_text(
        "[thresholds]\nmin_success_rate = 0.6\n"
        "[regressions]\nmax_success_rate_drop = 0.1\nforbid_new_categories = true\n",
        encoding="utf-8",
    )
    summary = tmp_path / "summary.md"

    # Act
    ok = cli("check", fixture_dir / CANDIDATE, "--rules", passing)
    bad = cli(
        "check",
        fixture_dir / CANDIDATE,
        "--rules",
        failing,
        "--baseline",
        fixture_dir / BASELINE,
        "--summary-md",
        summary,
    )

    # Assert
    ok.assert_exit(0)
    assert "check: 2 of 2 rule(s) passed" in ok.stdout
    bad.assert_exit(5)
    assert "FAIL min_success_rate" in bad.stdout
    assert "FAIL max_success_rate_drop" in bad.stdout
    assert "FAIL forbid_new_categories: new categories: tool:rerank" in bad.stdout
    assert "check: 0 of 3 rule(s) passed" in bad.stdout
    text = summary.read_text(encoding="utf-8")
    assert "0 of 3 rule(s) passed." in text
    assert "| `max_success_rate_drop` | **fail** | 0.3 | 0.1 |" in text


@pytest.mark.parametrize(
    ("rules_text", "extra", "message"),
    [
        ("[thresholds]\nmystery = 1\n", (), "unknown rule"),
        ("[regressions]\nmax_success_rate_drop = 0.1\n", (), "require --baseline"),
        ("[thresholds\n", (), "invalid TOML"),
    ],
)
def test_check_usage_errors_exit_two(
    cli: Callable[..., CommandResult],
    fixture_dir: Path,
    tmp_path: Path,
    rules_text: str,
    extra: tuple[str, ...],
    message: str,
) -> None:
    # Act
    result = cli("check", fixture_dir / CANDIDATE, "--rules", _rules(tmp_path, rules_text), *extra)

    # Assert
    result.assert_exit(2)
    assert message in result.stderr
    assert_no_traceback(result)


def test_check_missing_rules_file_is_an_io_error(
    cli: Callable[..., CommandResult], fixture_dir: Path, tmp_path: Path
) -> None:
    result = cli("check", fixture_dir / CANDIDATE, "--rules", tmp_path / "missing.toml")
    result.assert_exit(3)
    assert_no_traceback(result)
