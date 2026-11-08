"""Packaged, experimental field-mapping presets for documented vendor export shapes.

Presets are ordinary mapping documents; they add no vendor-specific code path.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

from journeygraph.exceptions import UsageError
from journeygraph.ingestion.mapping import FieldMapping, parse_mapping


@dataclass(frozen=True, slots=True)
class Preset:
    """Description of one packaged preset."""

    name: str
    tool: str
    input: str
    sources: tuple[str, ...]
    checked: str = "2026-11-08"
    maturity: str = "experimental"


PRESETS = (
    Preset(
        name="langfuse-observations",
        tool="Langfuse",
        input="enriched observations export (observations_v2/), JSON Lines",
        sources=(
            "https://langfuse.com/docs/api-and-data-platform/features/export-to-blob-storage",
        ),
    ),
    Preset(
        name="langsmith-runs",
        tool="LangSmith",
        input="run objects from runs.query / POST /api/v2/runs/query, one per line",
        sources=("https://docs.langchain.com/langsmith/smith-api/runs/query-runs",),
    ),
    Preset(
        name="phoenix-spans",
        tool="Arize Phoenix",
        input="REST API span objects, one per line",
        sources=(
            "https://arize.com/docs/phoenix/sdk-api-reference/rest-api/api-reference/spans/"
            "list-spans-with-simple-filters-no-dsl",
        ),
    ),
)
_BY_NAME = {preset.name: preset for preset in PRESETS}


def _unknown(name: str) -> UsageError:
    available = ", ".join(sorted(_BY_NAME))
    return UsageError(f"unknown preset {name!r}. Fix: choose one of {available}")


def preset_text(name: str) -> str:
    """Return the packaged TOML text of a preset."""

    if name not in _BY_NAME:
        raise _unknown(name)
    return files("journeygraph.data").joinpath(f"presets/{name}.toml").read_text(encoding="utf-8")


def load_preset(name: str) -> FieldMapping:
    """Parse a packaged preset into a field mapping."""

    return parse_mapping(preset_text(name))


def describe_presets() -> str:
    """Return a plain-text list of presets, their inputs, maturity, and sources."""

    lines: list[str] = []
    for preset in PRESETS:
        lines.append(f"{preset.name} ({preset.maturity}): {preset.tool} {preset.input}")
        lines.extend(f"  source (checked {preset.checked}): {url}" for url in preset.sources)
    return "\n".join(lines) + "\n"
