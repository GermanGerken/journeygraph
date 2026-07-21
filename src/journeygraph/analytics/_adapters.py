"""Small structural adapters at the analytics/domain boundary.

The domain package owns validation.  Analytics intentionally relies only on the stable
attributes in the public domain contract so its algorithms remain pure and independently
testable.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Protocol, cast


class EventLike(Protocol):
    @property
    def trace_id(self) -> str: ...

    @property
    def step_id(self) -> str: ...

    @property
    def operation_type(self) -> object: ...

    @property
    def component(self) -> object: ...

    @property
    def duration_ms(self) -> Decimal: ...

    @property
    def status(self) -> object: ...

    @property
    def outcome(self) -> object | None: ...

    @property
    def input_tokens(self) -> int | None: ...

    @property
    def output_tokens(self) -> int | None: ...

    @property
    def cost_usd(self) -> Decimal | None: ...

    @property
    def metadata(self) -> Mapping[str, object]: ...


class TraceLike(Protocol):
    @property
    def trace_id(self) -> str: ...

    @property
    def events(self) -> Sequence[EventLike]: ...

    @property
    def outcome(self) -> object: ...

    @property
    def outcome_source(self) -> object: ...


class DatasetLike(Protocol):
    @property
    def events(self) -> Sequence[EventLike]: ...

    @property
    def traces(self) -> Sequence[TraceLike]: ...

    @property
    def warnings(self) -> Sequence[object]: ...


def text(value: object) -> str:
    """Convert strings and string-valued enums to canonical text."""

    enum_value = getattr(value, "value", value)
    return str(enum_value)


def json_number(value: Decimal | int | float) -> int | float:
    """Convert a validated finite numeric value to a JSON-native number."""

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    if decimal_value == decimal_value.to_integral_value():
        return int(decimal_value)
    converted = float(decimal_value)
    if not math.isfinite(converted):
        raise ValueError("numeric aggregate is outside the supported JSON number range")
    return converted


def json_scalar(value: object) -> None | bool | int | float | str:
    """Return a deterministic JSON scalar for an allowlisted metadata value."""

    enum_value = getattr(value, "value", value)
    if enum_value is None or isinstance(enum_value, (bool, str)):
        return enum_value
    if isinstance(enum_value, (Decimal, int, float)):
        return json_number(enum_value)
    return str(enum_value)


def scalar_identity(value: object) -> str:
    """Produce a type-aware representation suitable for sorting and grouping."""

    scalar = json_scalar(value)
    representation = {
        "type": "null" if scalar is None else type(scalar).__name__,
        "value": scalar,
    }
    return json.dumps(representation, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _first_attribute(instance: object, names: tuple[str, ...]) -> object | None:
    for name in names:
        if hasattr(instance, name):
            return cast(object, getattr(instance, name))
    return None


def issue_payload(issue: object) -> dict[str, object]:
    """Adapt a public domain Issue to the stable analysis warning shape."""

    return {
        "code": text(_first_attribute(issue, ("code",)) or "unknown"),
        "severity": text(_first_attribute(issue, ("severity",)) or "warning"),
        "location": json_scalar(_first_attribute(issue, ("source_location", "location", "source"))),
        "message": text(_first_attribute(issue, ("message", "problem")) or ""),
        "hint": text(_first_attribute(issue, ("hint", "corrective_hint")) or ""),
    }


def issue_sort_key(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Return the documented stable warning sort key."""

    return tuple(text(payload.get(field, "")) for field in payload)
