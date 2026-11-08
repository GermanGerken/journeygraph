"""Thin command-line orchestration for JourneyGraph."""

from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, NoReturn

from journeygraph.analytics.rules import RulesError, evaluate_rules, parse_rules, summary_markdown
from journeygraph.api import (
    DEFAULT_MIN_SUPPORT,
    analyze_file,
    compare_files,
    validate_file,
    write_analysis,
    write_comparison,
)
from journeygraph.exceptions import (
    CHECK_FAILED_EXIT_CODE,
    FileOperationError,
    JourneyGraphError,
    UsageError,
)
from journeygraph.normalization import serialize_normalized_jsonl
from journeygraph.normalization.filters import TraceFilter, parse_outcomes, parse_timestamp
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


def _positive_int(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}") from None
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}")
    return parsed


def _timestamp(value: str) -> datetime:
    try:
        return parse_timestamp(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from None


def _trace_filter(parser: argparse.ArgumentParser, args: argparse.Namespace) -> TraceFilter:
    outcomes = None
    if args.outcome:
        try:
            outcomes = parse_outcomes(args.outcome)
        except ValueError as error:
            parser.error(f"argument --outcome: {error}")
    return TraceFilter(outcomes=outcomes, since=args.since, until=args.until)


def _add_analysis_options(parser: argparse.ArgumentParser) -> None:
    _add_format(parser)
    _add_metadata(parser)
    parser.add_argument(
        "--cohort-key",
        default="cohort",
        metavar="KEY",
        help="allowlisted metadata key used to segment traces (default: cohort)",
    )
    parser.add_argument(
        "--min-support",
        type=_positive_int,
        default=DEFAULT_MIN_SUPPORT,
        metavar="N",
        help=(
            "minimum traces or events behind a ranked finding "
            f"(positive integer; default: {DEFAULT_MIN_SUPPORT})"
        ),
    )
    parser.add_argument(
        "--outcome",
        action="append",
        default=[],
        metavar="OUTCOMES",
        help=(
            "keep only traces with these reconciled outcomes, comma-separated or repeated "
            "(success, failure, handoff, dropoff, unknown)"
        ),
    )
    parser.add_argument(
        "--since",
        type=_timestamp,
        metavar="TIMESTAMP",
        help="keep traces whose first event is at or after this ISO 8601 time (with offset or Z)",
    )
    parser.add_argument(
        "--until",
        type=_timestamp,
        metavar="TIMESTAMP",
        help="keep traces whose first event is before this ISO 8601 time (with offset or Z)",
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
            "normalized.jsonl, report.html, graph.svg. Diff artifacts: diff.json, diff.html. "
            "Exit codes: 0 success, 1 internal error, 2 validation/format/usage, 3 I/O, "
            "4 output conflict, 5 check rules failed."
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
    _add_analysis_options(analyze)
    analyze.add_argument(
        "--force", action="store_true", help="write fixed artifacts into a non-empty directory"
    )
    analyze.set_defaults(handler=_run_analyze)

    diff = subparsers.add_parser(
        "diff",
        help="compare a baseline and a candidate export and write diff.json and diff.html",
        description=(
            "Analyze two local files with identical options and report observed differences "
            "in outcomes, categories, transitions, path variants, and metrics."
        ),
    )
    diff.add_argument("baseline", type=Path, help="baseline local input file")
    diff.add_argument("candidate", type=Path, help="candidate local input file")
    diff.add_argument(
        "--output-dir", type=Path, required=True, help="destination directory for fixed artifacts"
    )
    _add_analysis_options(diff)
    diff.add_argument(
        "--force", action="store_true", help="write fixed artifacts into a non-empty directory"
    )
    diff.set_defaults(handler=_run_diff)

    check = subparsers.add_parser(
        "check",
        help="evaluate journey-level rules from a TOML file; exit 5 when any rule fails",
        description=(
            "Analyze a file and evaluate thresholds, plus regression limits against an optional "
            "baseline. Prints one line per rule."
        ),
    )
    check.add_argument("input", type=Path, help="local input file to check")
    check.add_argument("--rules", type=Path, required=True, help="TOML rules file")
    check.add_argument(
        "--baseline", type=Path, help="baseline local input file for [regressions] rules"
    )
    check.add_argument(
        "--summary-md", type=Path, metavar="PATH", help="also write a Markdown summary table"
    )
    _add_analysis_options(check)
    check.add_argument("--force", action="store_true", help="replace an existing --summary-md file")
    check.set_defaults(handler=_run_check)

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
        min_support=args.min_support,
        trace_filter=args.trace_filter,
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


def _analysis_options(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "input_format": args.input_format,
        "cohort_key": args.cohort_key,
        "allow_metadata_keys": args.allow_metadata_key,
        "min_support": args.min_support,
        "trace_filter": args.trace_filter,
    }


def _run_diff(args: argparse.Namespace) -> int:
    comparison = compare_files(args.baseline, args.candidate, **_analysis_options(args))
    diff_json, diff_html = write_comparison(comparison, args.output_dir, force=args.force)
    print(
        f"compared: {len(comparison.baseline.dataset.traces)} baseline trace(s), "
        f"{len(comparison.candidate.dataset.traces)} candidate trace(s)"
    )
    changes = comparison.diff.get("changes", [])
    for change in changes if isinstance(changes, list) else []:
        print(f"change: {change['statement']}")
    print(f"diff JSON: {diff_json}")
    print(f"HTML report: {diff_html}")
    return 0


def _run_check(args: argparse.Namespace) -> int:
    try:
        rules = parse_rules(args.rules.read_text(encoding="utf-8"))
    except OSError as error:
        raise FileOperationError(
            f"cannot read rules file {args.rules}: {error.strerror or error}"
        ) from error
    except (UnicodeDecodeError, RulesError) as error:
        raise UsageError(f"invalid rules file {args.rules}: {error}") from error
    if rules.needs_baseline and args.baseline is None:
        raise UsageError("[regressions] rules require --baseline")
    options = _analysis_options(args)
    report = analyze_file(args.input, **options).report
    baseline = analyze_file(args.baseline, **options).report if args.baseline else None
    results = evaluate_rules(rules, report, baseline)
    for result in results:
        print(f"{'PASS' if result.passed else 'FAIL'} {result.name}: {result.message}")
    failed = sum(1 for result in results if not result.passed)
    print(f"check: {len(results) - failed} of {len(results)} rule(s) passed")
    if args.summary_md is not None:
        write_text_file(
            args.summary_md, summary_markdown(results), force=args.force, input_path=args.input
        )
        print(f"summary: {args.summary_md}")
    return CHECK_FAILED_EXIT_CODE if failed else 0


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
    if getattr(args, "command", None) in {"analyze", "diff", "check"}:
        args.trace_filter = _trace_filter(parser, args)
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
