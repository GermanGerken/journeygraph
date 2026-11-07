"""Deterministic trace filters applied after normalization and before analysis."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from journeygraph.domain import Issue, NormalizedDataset
from journeygraph.domain.models import datetime_to_unix_ns
from journeygraph.exceptions import ValidationError

STANDARD_OUTCOMES = ("success", "failure", "handoff", "dropoff", "unknown")


@dataclass(frozen=True, slots=True)
class TraceFilter:
    """Which traces to keep: listed outcomes and a half-open first-event time window."""

    outcomes: tuple[str, ...] | None = None
    since: datetime | None = None
    until: datetime | None = None

    @property
    def is_empty(self) -> bool:
        """Return whether the filter keeps every trace."""

        return self.outcomes is None and self.since is None and self.until is None


def parse_outcomes(values: Iterable[str]) -> tuple[str, ...]:
    """Parse comma-separated outcome lists into a sorted, de-duplicated tuple."""

    outcomes = {
        part.strip().lower() for value in values for part in value.split(",") if part.strip()
    }
    unknown = sorted(outcomes - set(STANDARD_OUTCOMES))
    if not outcomes or unknown:
        listed = ", ".join(STANDARD_OUTCOMES)
        raise ValueError(f"expected one or more of {listed}; got {', '.join(unknown) or 'none'}")
    return tuple(outcome for outcome in STANDARD_OUTCOMES if outcome in outcomes)


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 timestamp that carries an explicit offset or ``Z``."""

    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        raise ValueError(f"expected an ISO 8601 timestamp, got {value!r}") from None
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {value!r} must include a UTC offset or Z")
    return parsed.astimezone(UTC)


def _format(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def describe_filter(trace_filter: TraceFilter, input_trace_count: int) -> dict[str, object]:
    """Return the payload description of a filter (without the retained count)."""

    return {
        "outcomes": list(trace_filter.outcomes) if trace_filter.outcomes is not None else None,
        "since": _format(trace_filter.since),
        "until": _format(trace_filter.until),
        "input_trace_count": input_trace_count,
    }


def filter_dataset(dataset: NormalizedDataset, trace_filter: TraceFilter) -> NormalizedDataset:
    """Keep traces matching the filter; reject a filter that keeps nothing."""

    if trace_filter.since and trace_filter.until and trace_filter.since >= trace_filter.until:
        raise ValidationError(
            (
                Issue(
                    "error",
                    "empty_time_window",
                    "--since/--until",
                    "The time window is empty because since is not before until.",
                    "Choose a since timestamp earlier than until.",
                ),
            )
        )
    if trace_filter.is_empty:
        return dataset

    since_ns = datetime_to_unix_ns(trace_filter.since) if trace_filter.since else None
    until_ns = datetime_to_unix_ns(trace_filter.until) if trace_filter.until else None
    kept = []
    for trace in dataset.traces:
        if trace_filter.outcomes is not None and str(trace.outcome) not in trace_filter.outcomes:
            continue
        start = trace.events[0].sort_key[0] if trace.events else None
        if since_ns is not None and (start is None or start < since_ns):
            continue
        if until_ns is not None and (start is None or start >= until_ns):
            continue
        kept.append(trace)

    if not kept:
        raise ValidationError(
            (
                Issue(
                    "error",
                    "filter_excluded_all_traces",
                    "trace filters",
                    f"The filters excluded all {len(dataset.traces)} accepted trace(s).",
                    "Widen --outcome, --since, or --until.",
                ),
            )
        )
    kept_ids = {trace.trace_id for trace in kept}
    return replace(
        dataset,
        traces=tuple(kept),
        events=tuple(event for event in dataset.events if event.trace_id in kept_ids),
    )
