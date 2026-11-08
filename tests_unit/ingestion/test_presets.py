"""Unit tests for packaged presets and the utc_naive timestamp unit."""

from __future__ import annotations

import pytest

from journeygraph.domain.models import SourceRecord
from journeygraph.exceptions import UsageError, ValidationError
from journeygraph.ingestion.mapping import apply_mapping, parse_mapping
from journeygraph.ingestion.presets import PRESETS, describe_presets, load_preset, preset_text

_MAPPING = """
mapping_version = "1"
[fields]
trace_id = "t"
step_id = "s"
timestamp = "at"
operation_type = "kind"
component = "name"
status = "state"
[timestamp]
unit = "utc_naive"
[duration]
start = "at"
end = "until"
"""


def _map(at: object, until: object = "2026-10-01 09:00:01") -> SourceRecord:
    record = SourceRecord(
        {"t": "a", "s": "b", "at": at, "until": until, "kind": "tool", "name": "x", "state": "ok"},
        "line 1",
        0,
    )
    return apply_mapping([record], parse_mapping(_MAPPING)).records[0]


@pytest.mark.parametrize(
    ("value", "timestamp", "timestamp_ns"),
    [
        ("2026-10-01 09:00:00", "2026-10-01T09:00:00.000000000Z", 1_790_845_200_000_000_000),
        ("2026-10-01T09:00:00.5", "2026-10-01T09:00:00.500000000Z", 1_790_845_200_500_000_000),
        (
            " 2026-10-01 09:00:00.123456 ",
            "2026-10-01T09:00:00.123456000Z",
            1_790_845_200_123_456_000,
        ),
        (
            "2026-10-01 09:00:00.000000001",
            "2026-10-01T09:00:00.000000001Z",
            1_790_845_200_000_000_001,
        ),
    ],
)
def test_utc_naive_timestamps_are_read_as_exact_utc(
    value: str, timestamp: str, timestamp_ns: int
) -> None:
    record = _map(value)
    assert record.data["timestamp"] == timestamp
    assert record.timestamp_ns == timestamp_ns


def test_utc_naive_duration_pairs_subtract_exactly() -> None:
    record = _map("2026-10-01 09:00:00.25", "2026-10-01 09:00:01")
    assert record.data["duration_ms"] == "750"


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-01T09:00:00Z",
        "2026-10-01 09:00:00+00:00",
        "2026-13-01 09:00:00",
        "2026-10-01",
        "2026-10-01 09:00:00.0000000001",
        1_790_845_200,
        None,
    ],
)
def test_utc_naive_rejects_offsets_and_malformed_values(value: object) -> None:
    with pytest.raises(ValidationError) as caught:
        _map(value)
    codes = {issue.code for issue in caught.value.issues}
    assert codes == {"mapped_value_invalid"}
    assert all("utc_naive" in issue.message for issue in caught.value.issues)


@pytest.mark.parametrize("preset", [preset.name for preset in PRESETS])
def test_every_packaged_preset_parses_and_cites_its_source(preset: str) -> None:
    mapping = load_preset(preset)
    text = preset_text(preset)
    assert mapping.fields["trace_id"].text
    assert "experimental" in text
    assert "checked on 2026-11-08" in text
    assert "https://" in text


def test_preset_listing_and_unknown_names() -> None:
    listing = describe_presets()
    assert listing.startswith("langfuse-observations (experimental): Langfuse")
    assert "phoenix-spans (experimental): Arize Phoenix" in listing
    assert listing.count("source (checked 2026-11-08): https://") == 2
    with pytest.raises(UsageError, match=r"unknown preset 'nope'\. Fix: choose one of langfuse"):
        preset_text("nope")
