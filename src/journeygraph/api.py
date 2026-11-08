"""Documented composition API for local validation, analysis, and reporting."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from journeygraph.analytics import DEFAULT_MIN_SUPPORT, analyze_dataset
from journeygraph.analytics.compare import compare_analyses
from journeygraph.domain.models import NormalizedDataset
from journeygraph.ingestion import read_records
from journeygraph.normalization import normalize_records
from journeygraph.normalization.filters import TraceFilter, describe_filter, filter_dataset
from journeygraph.normalization.privacy import normalize_metadata_key
from journeygraph.reporting import AnalysisArtifacts, write_analysis_artifacts
from journeygraph.reporting.diff_html import render_diff_html
from journeygraph.reporting.serialize import serialize_analysis
from journeygraph.reporting.writer import write_artifact_set
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
    min_support: int = DEFAULT_MIN_SUPPORT,
    trace_filter: TraceFilter | None = None,
) -> Analysis:
    """Validate, optionally filter, and analyze one local file with no filesystem output."""

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
    selected = trace_filter or TraceFilter()
    filters = describe_filter(selected, len(dataset.traces))
    dataset = filter_dataset(dataset, selected)
    report = analyze_dataset(
        dataset,
        cohort_key=normalized_cohort_key,
        tool_version=__version__,
        min_support=min_support,
        filters=filters,
    )
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


__all__ = [
    "DEFAULT_MIN_SUPPORT",
    "Analysis",
    "Comparison",
    "TraceFilter",
    "analyze_file",
    "compare_files",
    "validate_file",
    "write_analysis",
    "write_comparison",
]


@dataclass(frozen=True, slots=True)
class Comparison:
    """Two analyses produced with identical options and their comparison payload."""

    baseline: Analysis
    candidate: Analysis
    diff: Mapping[str, object]


def compare_files(
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    input_format: str = "auto",
    cohort_key: str | None = "cohort",
    allow_metadata_keys: Iterable[str] = (),
    min_support: int = DEFAULT_MIN_SUPPORT,
    trace_filter: TraceFilter | None = None,
) -> Comparison:
    """Analyze two local files with the same options and compare them."""

    options: dict[str, Any] = {
        "input_format": input_format,
        "cohort_key": cohort_key,
        "allow_metadata_keys": tuple(allow_metadata_keys),
        "min_support": min_support,
        "trace_filter": trace_filter,
    }
    baseline = analyze_file(baseline_path, **options)
    candidate = analyze_file(candidate_path, **options)
    diff = compare_analyses(baseline.report, candidate.report, min_support=min_support)
    return Comparison(baseline=baseline, candidate=candidate, diff=diff)


def write_comparison(
    comparison: Comparison, output_dir: str | Path, *, force: bool = False
) -> tuple[Path, ...]:
    """Publish ``diff.json`` and ``diff.html``."""

    rendered = {
        "diff.json": serialize_analysis(comparison.diff),
        "diff.html": render_diff_html(comparison.diff),
    }
    return write_artifact_set(
        rendered,
        output_dir,
        force=force,
        input_paths=(comparison.baseline.input_path, comparison.candidate.input_path),
    )
