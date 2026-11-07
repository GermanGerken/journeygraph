"""Unit tests for trace filters applied after normalization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest

from journeygraph.domain import CanonicalEvent, NormalizedDataset, Trace
from journeygraph.exceptions import ValidationError
from journeygraph.normalization.filters import (
    TraceFilter,
    describe_filter,
    filter_dataset,
    parse_outcomes,
    parse_timestamp,
)

BASE = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _event(trace_id: str, minute: int) -> CanonicalEvent:
    return CanonicalEvent(
        trace_id=trace_id,
        step_id="s1",
        parent_step_id=None,
        timestamp=BASE + timedelta(minutes=minute),
        operation_type="tool",
        component="t",
        duration_ms=Decimal(1),
        status="ok",
        outcome=None,
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
        metadata=MappingProxyType({}),
    )


def _dataset() -> NormalizedDataset:
    traces = (
        Trace("a", (_event("a", 0),), "success", "explicit"),
        Trace("b", (_event("b", 10),), "failure", "explicit"),
        Trace("c", (_event("c", 20),), "unknown", "missing"),
    )
    return NormalizedDataset(
        events=tuple(event for trace in traces for event in trace.events),
        traces=traces,
        warnings=(),
        input_format="jsonl",
        input_record_count=3,
    )


def _ids(dataset: NormalizedDataset) -> list[str]:
    return [trace.trace_id for trace in dataset.traces]


def test_empty_filter_returns_the_same_dataset() -> None:
    dataset = _dataset()
    assert filter_dataset(dataset, TraceFilter()) is dataset


def test_outcome_filter_keeps_listed_outcomes_and_their_events() -> None:
    # Act
    result = filter_dataset(_dataset(), TraceFilter(outcomes=("failure", "unknown")))

    # Assert
    assert _ids(result) == ["b", "c"]
    assert [event.trace_id for event in result.events] == ["b", "c"]
    assert result.input_record_count == 3


def test_time_window_is_half_open_on_the_first_event() -> None:
    # Act
    result = filter_dataset(
        _dataset(),
        TraceFilter(since=BASE + timedelta(minutes=10), until=BASE + timedelta(minutes=20)),
    )

    # Assert
    assert _ids(result) == ["b"]


def test_filters_that_exclude_everything_or_invert_the_window_are_errors() -> None:
    with pytest.raises(ValidationError, match="filter_excluded_all_traces"):
        filter_dataset(_dataset(), TraceFilter(outcomes=("handoff",)))
    with pytest.raises(ValidationError, match="empty_time_window"):
        filter_dataset(_dataset(), TraceFilter(since=BASE, until=BASE))


def test_parse_outcomes_accepts_commas_repeats_and_case() -> None:
    assert parse_outcomes(["Failure, success", "failure"]) == ("success", "failure")
    with pytest.raises(ValueError, match="bogus"):
        parse_outcomes(["success,bogus"])
    with pytest.raises(ValueError):
        parse_outcomes([" , "])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-10-01T09:00:00Z", BASE),
        ("2026-10-01T11:00:00+02:00", BASE),
        ("2026-10-01T09:00:00.5Z", BASE + timedelta(milliseconds=500)),
    ],
)
def test_parse_timestamp_normalizes_to_utc(text: str, expected: datetime) -> None:
    assert parse_timestamp(text) == expected


@pytest.mark.parametrize("text", ["2026-10-01T09:00:00", "yesterday", ""])
def test_parse_timestamp_requires_an_offset(text: str) -> None:
    with pytest.raises(ValueError):
        parse_timestamp(text)


def test_describe_filter_uses_canonical_utc_strings() -> None:
    description = describe_filter(
        TraceFilter(outcomes=("success",), since=BASE, until=None), input_trace_count=7
    )
    assert description == {
        "outcomes": ["success"],
        "since": "2026-10-01T09:00:00.000000Z",
        "until": None,
        "input_trace_count": 7,
    }
