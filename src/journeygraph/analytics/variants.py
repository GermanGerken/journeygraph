"""Explainable path variants and recurring short sequences.

Exact paths are often all unique on agent traces because of retries and repeated loops.
Variants group traces whose paths are equal after collapsing consecutive repeated blocks;
sequence patterns count short contiguous category sequences.  Both are deterministic, keep
references to the exact data they summarize, and describe associations only.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

MAX_BLOCK_LENGTH = 4
PATTERN_LENGTHS = (2, 3)
MAX_PATTERNS = 50

Step = tuple[tuple[str, ...], bool]


class TraceSequence(Protocol):
    """The per-trace data variants and patterns need."""

    @property
    def node_ids(self) -> tuple[str, ...]: ...

    @property
    def outcome(self) -> str: ...

    @property
    def path_id(self) -> str: ...


OutcomePayload = Callable[[Mapping[str, int], int], dict[str, object]]


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def collapse_repeats(sequence: Sequence[str]) -> tuple[Step, ...]:
    """Collapse consecutive repeated blocks of up to four items, preferring the shortest block.

    ``A B B B C`` becomes ``A, B+, C`` and ``A B C B C D`` becomes ``A, (B C)+, D``.  Each
    returned step is ``(block, repeated)``.
    """

    items = tuple(sequence)
    steps: list[Step] = []
    index = 0
    while index < len(items):
        for length in range(1, MAX_BLOCK_LENGTH + 1):
            block = items[index : index + length]
            if len(block) == length and items[index + length : index + 2 * length] == block:
                repetitions = 2
                while items[index + repetitions * length : index + (repetitions + 1) * length] == (
                    block
                ):
                    repetitions += 1
                steps.append((block, True))
                index += repetitions * length
                break
        else:
            steps.append(((items[index],), False))
            index += 1
    return tuple(steps)


def variant_id(steps: Sequence[Step]) -> str:
    """Return the versioned SHA-256 identity of a collapsed variant."""

    return _digest(["journeygraph.variant/v1", *([repeated, *block] for block, repeated in steps)])


def pattern_id(node_ids: Sequence[str]) -> str:
    """Return the versioned SHA-256 identity of a contiguous category sequence."""

    return _digest(["journeygraph.sequence/v1", *node_ids])


def _without_adjacent_repeats(sequence: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    for item in sequence:
        if not result or result[-1] != item:
            result.append(item)
    return tuple(result)


def path_variants(
    traces: Sequence[TraceSequence],
    labels: Mapping[str, str],
    outcome_payload: OutcomePayload,
) -> list[dict[str, object]]:
    """Group traces by collapsed variant, ordered by variant identity."""

    grouped: dict[str, list[TraceSequence]] = defaultdict(list)
    steps_by_id: dict[str, tuple[Step, ...]] = {}
    for trace in traces:
        steps = collapse_repeats(trace.node_ids)
        identity = variant_id(steps)
        steps_by_id[identity] = steps
        grouped[identity].append(trace)

    result: list[dict[str, object]] = []
    for identity in sorted(grouped):
        members = grouped[identity]
        path_ids = sorted({trace.path_id for trace in members})
        result.append(
            {
                "variant_id": identity,
                "steps": [
                    {
                        "node_ids": list(block),
                        "labels": [labels[node_id] for node_id in block],
                        "repeated": repeated,
                    }
                    for block, repeated in steps_by_id[identity]
                ],
                "trace_count": len(members),
                "rate": round(len(members) / len(traces), 12),
                "path_count": len(path_ids),
                "path_ids": path_ids,
                "trace_outcomes": outcome_payload(
                    Counter(trace.outcome for trace in members), len(members)
                ),
            }
        )
    return result


def sequence_patterns(
    traces: Sequence[TraceSequence],
    labels: Mapping[str, str],
    outcome_payload: OutcomePayload,
    *,
    min_support: int,
) -> list[dict[str, object]]:
    """Return recurring contiguous sequences over retry-collapsed paths."""

    outcomes: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    for trace in traces:
        collapsed = _without_adjacent_repeats(trace.node_ids)
        windows = {
            collapsed[start : start + length]
            for length in PATTERN_LENGTHS
            for start in range(len(collapsed) - length + 1)
        }
        for window in windows:
            outcomes[window][trace.outcome] += 1

    eligible = [
        (window, counts)
        for window, counts in outcomes.items()
        if sum(counts.values()) >= min_support
    ]
    eligible.sort(key=lambda item: (-sum(item[1].values()), -len(item[0]), pattern_id(item[0])))
    published = [
        {
            "pattern_id": pattern_id(window),
            "node_ids": list(window),
            "labels": [labels[node_id] for node_id in window],
            "length": len(window),
            "trace_count": sum(counts.values()),
            "trace_outcomes": outcome_payload(counts, sum(counts.values())),
        }
        for window, counts in eligible[:MAX_PATTERNS]
    ]
    return sorted(published, key=lambda item: str(item["pattern_id"]))
