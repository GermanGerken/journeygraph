"""Stable JSON serialization helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping


def serialize_analysis(report: Mapping[str, object]) -> str:
    """Serialize public analysis as deterministic, readable UTF-8 JSON."""

    return f"{json.dumps(report, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)}\n"


def serialize_embedded_analysis(report: Mapping[str, object]) -> str:
    """Serialize JSON safely inside a non-executable HTML data block."""

    value = json.dumps(
        report,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        value.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
