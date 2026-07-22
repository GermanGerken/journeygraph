"""Documented composition API for local validation, analysis, and reporting."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from journeygraph.analytics import analyze_dataset
from journeygraph.domain.models import NormalizedDataset
from journeygraph.ingestion import read_records
from journeygraph.normalization import normalize_records
from journeygraph.normalization.privacy import normalize_metadata_key
from journeygraph.reporting import AnalysisArtifacts, write_analysis_artifacts
from journeygraph.version import __version__


@dataclass(frozen=True, slots=True)
class Analysis:
    """One in-memory deterministic analysis and its normalized source dataset."""

    dataset: NormalizedDataset
    report: Mapping[str, object]
    input_path: Path


def validate_file(
    input_path: str | Path,
    *,
    input_format: str = "auto",
    allow_metadata_keys: Iterable[str] = (),
) -> NormalizedDataset:
    """Read and validate a local input file without writing output."""

    records = read_records(input_path, input_format)
    selected_format = input_format
    if input_format == "auto":
        suffix = Path(input_path).suffix.casefold()
        selected_format = {
            ".jsonl": "jsonl",
            ".ndjson": "jsonl",
            ".csv": "csv",
            ".parquet": "parquet",
            ".pq": "parquet",
        }.get(suffix, "auto")
    return normalize_records(
        records,
        input_format=selected_format,
        allow_metadata_keys=allow_metadata_keys,
    )


def analyze_file(
    input_path: str | Path,
    *,
    input_format: str = "auto",
    cohort_key: str | None = "cohort",
    allow_metadata_keys: Iterable[str] = (),
) -> Analysis:
    """Validate and analyze one local file with no filesystem output."""

    resolved_input_path = Path(input_path).resolve()
    retained_keys = tuple(allow_metadata_keys)
    normalized_cohort_key = normalize_metadata_key(cohort_key) if cohort_key is not None else None
    if normalized_cohort_key is not None and normalized_cohort_key not in retained_keys:
        retained_keys = (*retained_keys, normalized_cohort_key)
    dataset = validate_file(
        resolved_input_path,
        input_format=input_format,
        allow_metadata_keys=retained_keys,
    )
    report = analyze_dataset(dataset, cohort_key=normalized_cohort_key, tool_version=__version__)
    return Analysis(dataset=dataset, report=report, input_path=resolved_input_path)


def write_analysis(
    analysis: Analysis,
    output_dir: str | Path,
    *,
    force: bool = False,
    extra_files: Mapping[str, str] | None = None,
) -> AnalysisArtifacts:
    """Publish JSON, canonical JSONL, HTML, SVG, and optional fixed-name artifacts."""

    return write_analysis_artifacts(
        analysis.report,
        analysis.dataset,
        output_dir,
        force=force,
        extra_files=extra_files,
        input_path=analysis.input_path,
    )


__all__ = ["Analysis", "analyze_file", "validate_file", "write_analysis"]
