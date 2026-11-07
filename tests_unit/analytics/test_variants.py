"""Unit tests for path variants, sequence patterns, and sequence-association findings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from journeygraph.analytics import build_findings
from journeygraph.analytics.variants import (
    MAX_PATTERNS,
    collapse_repeats,
    path_variants,
    pattern_id,
    sequence_patterns,
    variant_id,
)


@dataclass(frozen=True)
class _Trace:
    node_ids: tuple[str, ...]
    outcome: str
    path_id: str = ""


def _payload(counts: Mapping[str, int], total: int) -> dict[str, object]:
    return {"counts": dict(sorted(counts.items())), "rates": {"total": total}}


def _trace(path: str, outcome: str = "success") -> _Trace:
    return _Trace(tuple(path.split()), outcome, path_id=path)


LABELS = {name: f"step:{name}" for name in "ABCDEFGH"}


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        ("", ()),
        ("A", ((("A",), False),)),
        ("A B B B C", ((("A",), False), (("B",), True), (("C",), False))),
        ("A B C B C D", ((("A",), False), (("B", "C"), True), (("D",), False))),
        ("A B A B A", ((("A", "B"), True), (("A",), False))),
        ("A A B A A B", ((("A",), True), (("B",), False), (("A",), True), (("B",), False))),
        ("A B C D A B C D", ((("A", "B", "C", "D"), True),)),
        (
            "A B C D E A B C D E",
            tuple(((item,), False) for item in ["A", "B", "C", "D", "E", "A", "B", "C", "D", "E"]),
        ),
        ("A B C A B C A B C X", ((("A", "B", "C"), True), (("X",), False))),
    ],
)
def test_collapse_repeats_prefers_shortest_block_up_to_four(
    sequence: str, expected: tuple[tuple[tuple[str, ...], bool], ...]
) -> None:
    assert collapse_repeats(sequence.split()) == expected


@given(st.lists(st.sampled_from("ABC"), max_size=30))
def test_collapse_repeats_never_loses_order_and_has_no_adjacent_equal_singletons(
    items: list[str],
) -> None:
    # Act
    steps = collapse_repeats(items)

    # Assert: expanding each repeated block at least once preserves the category order.
    flattened = [item for block, _ in steps for item in block]
    remaining = iter(items)
    assert all(item in remaining for item in flattened)
    assert set(flattened) == set(items)
    assert all(not (first == second and not first[1]) for first, second in pairwise(steps))


def test_identities_are_versioned_and_distinguish_repetition() -> None:
    once = collapse_repeats(["A", "B"])
    repeated = collapse_repeats(["A", "B", "B"])
    assert variant_id(once) != variant_id(repeated)
    assert variant_id(once) == variant_id(collapse_repeats(["A", "B"]))
    assert pattern_id(["A", "B"]) != pattern_id(["B", "A"])
    assert len(variant_id(once)) == len(pattern_id(["A"])) == 64


def test_path_variants_group_traces_and_keep_exact_path_references() -> None:
    # Arrange
    traces = [
        _trace("A B B C"),
        _trace("A B B B C", "failure"),
        _trace("A B C"),
        _trace("A B B C"),
    ]

    # Act
    variants = path_variants(traces, LABELS, _payload)

    # Assert
    by_count = sorted(variants, key=lambda item: -int(item["trace_count"]))  # type: ignore[call-overload]
    collapsed, plain = by_count
    assert collapsed["trace_count"] == 3
    assert collapsed["path_count"] == 2
    assert collapsed["path_ids"] == ["A B B B C", "A B B C"]
    assert collapsed["rate"] == 0.75
    assert collapsed["trace_outcomes"]["counts"] == {"failure": 1, "success": 2}
    assert collapsed["steps"] == [
        {"node_ids": ["A"], "labels": ["step:A"], "repeated": False},
        {"node_ids": ["B"], "labels": ["step:B"], "repeated": True},
        {"node_ids": ["C"], "labels": ["step:C"], "repeated": False},
    ]
    assert plain["trace_count"] == 1
    assert [item["variant_id"] for item in variants] == sorted(
        str(item["variant_id"]) for item in variants
    )


def test_sequence_patterns_use_retry_collapsed_windows_and_distinct_traces() -> None:
    # Arrange: "A A B" must contribute "A B", never "A A"; B C B C counts per trace once.
    traces = [_trace("A A B C"), _trace("A B C B C"), _trace("A B"), _trace("C A")]

    # Act
    patterns = sequence_patterns(traces, LABELS, _payload, min_support=2)

    # Assert
    found = {tuple(item["node_ids"]): item["trace_count"] for item in patterns}  # type: ignore[arg-type]
    assert found == {("A", "B"): 3, ("B", "C"): 2, ("A", "B", "C"): 2}
    assert all(item["length"] == len(item["node_ids"]) for item in patterns)  # type: ignore[arg-type]
    assert [item["pattern_id"] for item in patterns] == sorted(
        str(item["pattern_id"]) for item in patterns
    )


def test_sequence_patterns_are_capped_by_support_then_length() -> None:
    # Arrange: 60 distinct two-step windows, each in its own pair of traces.
    traces = [_trace(f"N{index} M{index}") for index in range(MAX_PATTERNS + 10) for _ in range(2)]
    traces.extend(_trace("N0 M0") for _ in range(3))
    labels = {node: node for trace in traces for node in trace.node_ids}

    # Act
    patterns = sequence_patterns(traces, labels, _payload, min_support=2)

    # Assert
    assert len(patterns) == MAX_PATTERNS
    assert ["N0", "M0"] in [item["node_ids"] for item in patterns]


def _report(
    patterns: list[dict[str, object]], nodes: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "outcomes": {"counts": {"success": 10, "failure": 10, "unknown": 0}},
        "nodes": nodes or [],
        "sequence_patterns": patterns,
        "totals": {"traces": 20},
    }


def _pattern(ids: list[str], success: int, failure: int, unknown: int = 0) -> dict[str, object]:
    return {
        "pattern_id": pattern_id(ids),
        "node_ids": ids,
        "labels": [f"step:{item}" for item in ids],
        "trace_outcomes": {"counts": {"success": success, "failure": failure, "unknown": unknown}},
    }


def test_sequence_association_reports_labels_and_pattern_identity() -> None:
    # Arrange: 8 of 8 matching traces succeed versus 2 of 12 others.
    report = _report([_pattern(["A", "B"], 8, 0, unknown=2)])

    # Act
    items = build_findings(report)["items"]

    # Assert
    assert isinstance(items, list) and len(items) == 1
    finding = items[0]
    assert finding["kind"] == "sequence_association"
    assert finding["node_id"] is None
    assert finding["pattern_id"] == pattern_id(["A", "B"])
    assert finding["labels"] == ["step:A", "step:B"]
    assert finding["label"] == "step:A → step:B"
    assert finding["value"] == 1.0
    assert finding["baseline"] == pytest.approx(2 / 12)
    assert "2 matching trace(s) with an unknown outcome" in str(finding["statement"])


def test_sequence_association_skips_sequences_a_category_already_explains() -> None:
    # Arrange: node B alone carries exactly the same trace counts as the sequence A -> B.
    node = {
        "id": "B",
        "label": "step:B",
        "trace_outcomes": {"counts": {"success": 8, "failure": 0, "unknown": 0}},
    }
    report = _report([_pattern(["A", "B"], 8, 0)], nodes=[node])

    # Act
    kinds = [item["kind"] for item in build_findings(report)["items"]]  # type: ignore[union-attr]

    # Assert
    assert kinds == ["outcome_association"]


def test_sequence_association_reports_identical_count_groups_once_preferring_shorter() -> None:
    # Arrange
    report = _report(
        [
            _pattern(["A", "B", "C"], 0, 6),
            _pattern(["B", "C"], 0, 6),
            _pattern(["A", "B"], 0, 6),
            _pattern(["C", "D"], 5, 1),
        ]
    )

    # Act
    items = build_findings(report)["items"]

    # Assert
    assert isinstance(items, list)
    lengths = sorted(len(item["labels"]) for item in items)
    assert lengths == [2, 2]
    first_pair = min(pattern_id(["A", "B"]), pattern_id(["B", "C"]))
    assert first_pair in {item["pattern_id"] for item in items}


def test_sequence_association_respects_support_and_threshold() -> None:
    report = _report([_pattern(["A", "B"], 2, 0), _pattern(["C", "D"], 5, 5)])
    assert build_findings(report)["items"] == []
