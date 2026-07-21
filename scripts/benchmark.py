"""Deterministic local scaling scenario; not a universal performance claim."""

from __future__ import annotations

import argparse
import json
import tempfile
import tracemalloc
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import TypeVar

from journeygraph.analytics import analyze_dataset
from journeygraph.graph import build_graph
from journeygraph.ingestion import read_records
from journeygraph.normalization import normalize_records
from journeygraph.reporting.html import render_html
from journeygraph.reporting.serialize import serialize_analysis
from journeygraph.reporting.svg import render_svg

T = TypeVar("T")


def _measure(action: Callable[[], T]) -> tuple[T, float]:
    started = perf_counter()
    result = action()
    return result, perf_counter() - started


def _write_dataset(path: Path, traces: int, steps: int) -> int:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    operations = ("request", "router", "retrieval", "model", "tool", "validation")
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as target:
        for trace_index in range(traces):
            trace_id = f"bench-{trace_index:07d}"
            for step_index in range(steps):
                operation = operations[step_index % len(operations)]
                component = f"{operation}-component"
                record: dict[str, object] = {
                    "schema_version": "1.0",
                    "trace_id": trace_id,
                    "step_id": f"step-{step_index:03d}",
                    "timestamp": (base + timedelta(seconds=trace_index * steps + step_index))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "operation_type": operation,
                    "component": component,
                    "duration_ms": 5 + (step_index % 11),
                    "status": "ok",
                    "metadata": {"cohort": f"cohort-{trace_index % 4}"},
                }
                if step_index:
                    record["parent_step_id"] = f"step-{step_index - 1:03d}"
                if operation == "model":
                    record.update(
                        {
                            "input_tokens": 100 + step_index,
                            "output_tokens": 20 + step_index,
                            "cost_usd": 0.001 + step_index / 1_000_000,
                        }
                    )
                if step_index == steps - 1:
                    remainder = trace_index % 10
                    if remainder < 7:
                        record["outcome"] = "success"
                    elif remainder == 7:
                        record["outcome"] = "failure"
                        record["status"] = "error"
                    elif remainder == 8:
                        record["outcome"] = "handoff"
                target.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
                target.write("\n")
                count += 1
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", type=int, default=2000)
    parser.add_argument("--steps", type=int, default=12)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run and print one JSON measurement record."""

    args = build_parser().parse_args(argv)
    if args.traces <= 0 or args.steps <= 0:
        raise SystemExit("--traces and --steps must be positive")
    tracemalloc.start()
    with tempfile.TemporaryDirectory(prefix="journeygraph-benchmark-") as temporary:
        input_path = Path(temporary) / "benchmark.jsonl"
        row_count = _write_dataset(input_path, args.traces, args.steps)
        records, ingestion_seconds = _measure(lambda: read_records(input_path, "jsonl"))
        dataset, normalization_seconds = _measure(
            lambda: normalize_records(records, input_format="jsonl")
        )
        _graph, graph_seconds = _measure(lambda: build_graph(dataset))
        analysis, full_analysis_seconds = _measure(lambda: analyze_dataset(dataset))

        def render() -> int:
            return sum(
                len(value.encode("utf-8"))
                for value in (
                    serialize_analysis(analysis),
                    render_html(analysis),
                    render_svg(analysis),
                )
            )

        rendered_bytes, reporting_seconds = _measure(render)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result = {
        "schema_version": "1.0",
        "scenario": {
            "traces": args.traces,
            "steps_per_trace": args.steps,
            "events": row_count,
        },
        "seconds": {
            "ingestion": round(ingestion_seconds, 6),
            "normalization": round(normalization_seconds, 6),
            "graph_standalone": round(graph_seconds, 6),
            "analysis_including_graph": round(full_analysis_seconds, 6),
            "reporting": round(reporting_seconds, 6),
            "end_to_end_total": round(
                ingestion_seconds
                + normalization_seconds
                + full_analysis_seconds
                + reporting_seconds,
                6,
            ),
        },
        "peak_memory_mib": round(peak / (1024 * 1024), 3),
        "rendered_bytes": rendered_bytes,
        "note": (
            "Local diagnostic only; no universal performance threshold or claim. "
            "graph_standalone is a diagnostic submeasurement and is excluded from "
            "end_to_end_total because analysis_including_graph builds the graph again."
        ),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
