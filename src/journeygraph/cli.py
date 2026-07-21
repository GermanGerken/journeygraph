"""Thin command-line orchestration for JourneyGraph."""

from __future__ import annotations

import argparse
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import NoReturn

from journeygraph.api import analyze_file, validate_file, write_analysis
from journeygraph.exceptions import JourneyGraphError
from journeygraph.normalization import serialize_normalized_jsonl
from journeygraph.reporting.writer import write_text_file
from journeygraph.version import __version__

_FORMATS = ("auto", "jsonl", "csv", "parquet", "otlp-json")


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--format",
        dest="input_format",
        choices=_FORMATS,
        default="auto",
        help="input format (OTLP/JSON must be selected explicitly; default: infer by extension)",
    )


def _add_metadata(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-metadata-key",
        action="append",
        default=[],
        metavar="KEY",
        help="retain an additional safe operational metadata key (repeatable)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the complete public CLI parser."""

    parser = argparse.ArgumentParser(
        prog="journeygraph",
        description=(
            "Local-first graph analytics for recurring paths, loops, failures, and outcomes "
            "across AI-agent traces and event data."
        ),
        epilog=(
            "Formats: jsonl, csv, parquet, otlp-json. Analyze/demo artifacts: analysis.json, "
            "normalized.jsonl, report.html, graph.svg. Exit codes: 0 success, 1 internal "
            "error, 2 validation/format, 3 I/O, 4 output conflict."
        ),
    )
    parser.add_argument("--version", action="version", version=f"JourneyGraph {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate",
        help="validate and privacy-filter an input file",
        description="Validate canonical events or a supported trace export without analyzing it.",
    )
    validate.add_argument("input", type=Path, help="local input file")
    _add_format(validate)
    _add_metadata(validate)
    validate.add_argument(
        "--normalized-out",
        type=Path,
        help="optional canonical JSONL output path",
    )
    validate.add_argument(
        "--force", action="store_true", help="replace the explicit normalized output file"
    )
    validate.set_defaults(handler=_run_validate)

    analyze = subparsers.add_parser(
        "analyze",
        help="analyze a file and write JSON, HTML, SVG, and normalized output",
        description="Build a deterministic aggregate journey graph and local analytical report.",
    )
    analyze.add_argument("input", type=Path, help="local input file")
    analyze.add_argument(
        "--output-dir", type=Path, required=True, help="destination directory for fixed artifacts"
    )
    _add_format(analyze)
    _add_metadata(analyze)
    analyze.add_argument(
        "--cohort-key",
        default="cohort",
        metavar="KEY",
        help="allowlisted metadata key used to segment traces (default: cohort)",
    )
    analyze.add_argument(
        "--force", action="store_true", help="write fixed artifacts into a non-empty directory"
    )
    analyze.set_defaults(handler=_run_analyze)

    demo = subparsers.add_parser(
        "demo",
        help="generate and analyze deterministic synthetic AI-agent traces",
        description=(
            "Create a complete local report from packaged synthetic data; no network is used."
        ),
    )
    demo.add_argument(
        "--output-dir",
        type=Path,
        default=Path("journeygraph-demo"),
        help="destination directory (default: journeygraph-demo)",
    )
    demo.add_argument(
        "--force", action="store_true", help="write fixed artifacts into a non-empty directory"
    )
    demo.set_defaults(handler=_run_demo)
    return parser


def _print_warnings(warnings: tuple[object, ...]) -> None:
    for warning in warnings:
        formatter = getattr(warning, "format", None)
        text = formatter() if callable(formatter) else str(warning)
        print(f"warning: {text}")


def _run_validate(args: argparse.Namespace) -> int:
    dataset = validate_file(
        args.input,
        input_format=args.input_format,
        allow_metadata_keys=args.allow_metadata_key,
    )
    if args.normalized_out is not None:
        write_text_file(
            args.normalized_out,
            serialize_normalized_jsonl(dataset),
            force=args.force,
            input_path=args.input,
        )
        print(f"normalized output: {args.normalized_out}")
    print(
        f"valid: {len(dataset.events)} event(s), {len(dataset.traces)} trace(s), "
        f"{len(dataset.warnings)} warning(s)"
    )
    _print_warnings(dataset.warnings)
    return 0


def _run_analyze(args: argparse.Namespace) -> int:
    analysis = analyze_file(
        args.input,
        input_format=args.input_format,
        cohort_key=args.cohort_key,
        allow_metadata_keys=args.allow_metadata_key,
    )
    artifacts = write_analysis(analysis, args.output_dir, force=args.force)
    print(
        f"analyzed: {len(analysis.dataset.events)} event(s), "
        f"{len(analysis.dataset.traces)} trace(s)"
    )
    print(f"analysis JSON: {artifacts.analysis_json}")
    print(f"HTML report: {artifacts.html_report}")
    print(f"SVG graph: {artifacts.svg_graph}")
    _print_warnings(analysis.dataset.warnings)
    return 0


def _run_demo(args: argparse.Namespace) -> int:
    demo_text = files("journeygraph.data").joinpath("demo.jsonl").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="journeygraph-demo-") as temporary:
        input_path = Path(temporary) / "demo.jsonl"
        input_path.write_text(demo_text, encoding="utf-8")
        analysis = analyze_file(input_path, input_format="jsonl", cohort_key="cohort")
    artifacts = write_analysis(
        analysis,
        args.output_dir,
        force=args.force,
        extra_files={"demo-traces.jsonl": demo_text},
    )
    print(
        f"demo complete: {len(analysis.dataset.events)} event(s), "
        f"{len(analysis.dataset.traces)} trace(s)"
    )
    print(f"synthetic input: {artifacts.extra_files[0]}")
    print(f"analysis JSON: {artifacts.analysis_json}")
    print(f"HTML report: {artifacts.html_report}")
    print(f"SVG graph: {artifacts.svg_graph}")
    return 0


def _unexpected(error: Exception) -> NoReturn:
    print(
        f"error: unexpected internal failure ({type(error).__name__}). "
        "Please report this with the command and a minimal sanitized input.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and map expected failures to documented exit codes."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        handler = args.handler
        return int(handler(args))
    except JourneyGraphError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit_code
    except (KeyboardInterrupt, BrokenPipeError):
        return 1
    except Exception as error:  # A stable CLI boundary must not expose local tracebacks.
        _unexpected(error)
