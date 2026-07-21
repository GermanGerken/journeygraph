"""Small immutable contracts shared by the JourneyGraph pipeline."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

Severity = Literal["warning", "error"]
Status = Literal["unset", "ok", "error"]
Outcome = Literal["success", "failure", "handoff", "dropoff", "unknown"]
_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def datetime_to_unix_ns(value: datetime) -> int:
    """Convert an aware UTC-compatible datetime to exact integer Unix nanoseconds."""

    delta = value.astimezone(UTC) - _UNIX_EPOCH
    return ((delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds) * 1_000


def decimal_to_json_number(value: Decimal) -> int | float:
    """Return a JSON number while keeping integral values readable."""

    if value == value.to_integral_value():
        return int(value)
    converted = float(value)
    if not math.isfinite(converted):
        raise ValueError("decimal value is outside the supported JSON number range")
    return converted


@dataclass(frozen=True, slots=True)
class Issue:
    """A stable, actionable validation or data-quality observation."""

    severity: Severity
    code: str
    location: str
    message: str
    hint: str

    def format(self) -> str:
        """Format the issue without echoing an input value."""

        return f"[{self.code}] {self.location}: {self.message} Fix: {self.hint}"

    def to_dict(self) -> dict[str, str]:
        """Return the public JSON representation."""

        return {
            "severity": self.severity,
            "code": self.code,
            "location": self.location,
            "message": self.message,
            "hint": self.hint,
        }


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """One decoded source record and its safe source location."""

    data: Mapping[str, object]
    location: str
    sequence: int
    timestamp_ns: int | None = None


@dataclass(frozen=True, slots=True)
class CanonicalEvent:
    """One validated, normalized event/span."""

    trace_id: str
    step_id: str
    parent_step_id: str | None
    timestamp: datetime
    operation_type: str
    component: str
    duration_ms: Decimal
    status: Status
    outcome: Outcome | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    metadata: Mapping[str, str | int | float | bool | None] = field(
        default_factory=lambda: MappingProxyType({})
    )
    timestamp_ns: int | None = None

    @property
    def category(self) -> tuple[str, str]:
        """Return the aggregate node identity before hashing."""

        return (self.operation_type, self.component)

    @property
    def label(self) -> str:
        """Return the deterministic human-readable category label."""

        return f"{self.operation_type}:{self.component}"

    @property
    def total_tokens(self) -> int | None:
        """Return token total when at least one part is present."""

        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)

    @property
    def sort_key(self) -> tuple[int, str]:
        """Return an exact deterministic chronological ordering key."""

        timestamp_ns = self.timestamp_ns
        if timestamp_ns is None:
            timestamp_ns = datetime_to_unix_ns(self.timestamp)
        return (timestamp_ns, self.step_id)

    def to_dict(self) -> dict[str, object]:
        """Return the canonical privacy-filtered JSON object."""

        timestamp = self.timestamp.astimezone(UTC).isoformat(timespec="microseconds")
        timestamp = f"{timestamp[:-6]}Z"
        if self.timestamp_ns is not None and self.timestamp_ns % 1_000:
            seconds, nanoseconds = divmod(self.timestamp_ns, 1_000_000_000)
            timestamp_base = datetime.fromtimestamp(seconds, tz=UTC)
            timestamp = f"{timestamp_base:%Y-%m-%dT%H:%M:%S}.{nanoseconds:09d}Z"
        result: dict[str, object] = {
            "schema_version": "1.0",
            "trace_id": self.trace_id,
            "step_id": self.step_id,
            "timestamp": timestamp,
            "operation_type": self.operation_type,
            "component": self.component,
            "duration_ms": decimal_to_json_number(self.duration_ms),
            "status": self.status,
        }
        optional: tuple[tuple[str, object | None], ...] = (
            ("parent_step_id", self.parent_step_id),
            ("outcome", self.outcome),
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
            (
                "cost_usd",
                decimal_to_json_number(self.cost_usd) if self.cost_usd is not None else None,
            ),
        )
        result.update({key: value for key, value in optional if value is not None})
        if self.metadata:
            result["metadata"] = dict(sorted(self.metadata.items()))
        return result


@dataclass(frozen=True, slots=True)
class Trace:
    """A normalized session with a single reconciled outcome."""

    trace_id: str
    events: tuple[CanonicalEvent, ...]
    outcome: Outcome
    outcome_source: Literal["explicit", "terminal_status", "missing"]

    @property
    def labels(self) -> tuple[str, ...]:
        """Return the ordered analytical path labels."""

        return tuple(event.label for event in self.events)


@dataclass(frozen=True, slots=True)
class NormalizedDataset:
    """Accepted events, grouped traces, and non-blocking observations."""

    events: tuple[CanonicalEvent, ...]
    traces: tuple[Trace, ...]
    warnings: tuple[Issue, ...]
    input_format: str
    input_record_count: int
