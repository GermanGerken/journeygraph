"""Self-contained, escaped HTML analytical report."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape

from journeygraph.reporting.serialize import serialize_embedded_analysis
from journeygraph.reporting.svg import render_svg


def _mapping_list(report: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = report.get(key, [])
    if not isinstance(value, Sequence):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _value(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.6g}"
    return str(value)


def _cell(value: object) -> str:
    return escape(_value(value), quote=True)


def _path_label(item: Mapping[str, object]) -> str:
    labels = item.get("labels", [])
    if isinstance(labels, Sequence) and not isinstance(labels, (str, bytes)):
        return " → ".join(str(label) for label in labels)
    return str(labels)


def _success_rate(item: Mapping[str, object]) -> object:
    direct = item.get("success_rate")
    if direct is not None:
        return direct
    rates = item.get("outcome_rates", {})
    if isinstance(rates, Mapping):
        return rates.get("success", "—")
    return "—"


def _sort_number(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return 0.0


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]], empty: str) -> str:
    if not rows:
        return f'<p class="empty">{escape(empty)}</p>'
    head = "".join(f'<th scope="col">{escape(header)}</th>' for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_cell(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def render_html(report: Mapping[str, object]) -> str:
    """Render a local report with no executable script or remote dependency."""

    totals = report.get("totals", {})
    total_values = totals if isinstance(totals, Mapping) else {}
    outcomes = report.get("outcomes", {})
    outcome_values = outcomes.get("counts", outcomes) if isinstance(outcomes, Mapping) else {}
    if not isinstance(outcome_values, Mapping):
        outcome_values = {}
    paths = _mapping_list(report, "paths")
    transitions = _mapping_list(report, "transitions")
    retries = _mapping_list(report, "retries")
    loops = _mapping_list(report, "loops")
    failures = _mapping_list(report, "failure_points")
    dropoffs = _mapping_list(report, "dropoff_points")
    cohort_container = report.get("cohorts", {})
    cohort_items = (
        cohort_container.get("items", []) if isinstance(cohort_container, Mapping) else []
    )
    cohorts = (
        [item for item in cohort_items if isinstance(item, Mapping)]
        if isinstance(cohort_items, Sequence)
        else []
    )
    warnings = _mapping_list(report, "warnings")
    metrics = report.get("metrics", {})
    metric_values = metrics if isinstance(metrics, Mapping) else {}

    cards = "".join(
        f'<article class="card"><span>{escape(label)}</span><strong>{_cell(value)}</strong></article>'
        for label, value in (
            ("Traces", total_values.get("traces", 0)),
            ("Events", total_values.get("events", 0)),
            ("Success", outcome_values.get("success", 0)),
            ("Failure", outcome_values.get("failure", 0)),
            ("Handoff", outcome_values.get("handoff", 0)),
            ("Drop-off", outcome_values.get("dropoff", 0)),
        )
    )
    frequent_paths = sorted(
        paths,
        key=lambda path: (-_sort_number(path.get("count", 0)), str(path.get("path_id", ""))),
    )[:20]
    frequent_transitions = sorted(
        transitions,
        key=lambda transition: (
            -_sort_number(transition.get("weight", 0)),
            str(transition.get("source", "")),
            str(transition.get("target", "")),
        ),
    )[:30]
    path_rows = [
        (
            _path_label(path),
            path.get("count", 0),
            path.get("success_rate", "—"),
            path.get("outcomes", {}),
        )
        for path in frequent_paths
    ]
    transition_rows = [
        (
            transition.get("source_label", transition.get("source", "")),
            transition.get("target_label", transition.get("target", "")),
            transition.get("weight", 0),
            transition.get("trace_count", 0),
        )
        for transition in frequent_transitions
    ]
    retry_rows = [
        (
            retry.get("label", _path_label(retry)),
            retry.get("count", retry.get("occurrence_count", 0)),
            retry.get("trace_count", 0),
        )
        for retry in retries
    ]
    loop_rows = [
        (
            _path_label(loop),
            loop.get("count", loop.get("occurrence_count", 0)),
            loop.get("trace_count", 0),
        )
        for loop in loops
    ]
    point_rows = [
        (
            point.get("label", point.get("node_id", point.get("id", ""))),
            point.get("error_event_count", 0),
            point.get("terminal_failure_count", 0),
            point.get("trace_count", 0),
        )
        for point in failures
    ]
    dropoff_rows = [
        (
            point.get("label", point.get("node_id", point.get("id", ""))),
            point.get("count", point.get("trace_count", 0)),
        )
        for point in dropoffs
    ]
    cohort_rows = [
        (
            cohort.get("value", cohort.get("cohort", "")),
            cohort.get("trace_count", cohort.get("traces", cohort.get("count", 0))),
            _success_rate(cohort),
            cohort.get("outcomes", {}),
        )
        for cohort in cohorts
    ]
    warning_rows = [
        (
            warning.get("code", ""),
            warning.get("location", ""),
            warning.get("message", ""),
            warning.get("hint", ""),
        )
        for warning in warnings
    ]
    metric_rows: list[tuple[object, ...]] = []
    for metric_name, summary in sorted(metric_values.items()):
        if isinstance(summary, Mapping):
            metric_rows.append(
                (
                    metric_name,
                    summary.get("count", 0),
                    summary.get("missing_count", summary.get("missing", 0)),
                    summary.get("sum", summary.get("total", "—")),
                    summary.get("mean", "—"),
                    summary.get("p95", "—"),
                )
            )

    embedded = serialize_embedded_analysis(report)
    svg = render_svg(report)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
  <title>JourneyGraph analysis report</title>
  <style>
    :root {{ color-scheme: light; --ink:#18213a; --muted:#59647d; --line:#dce1ed; --accent:#3256a8; --paper:#fff; --wash:#f3f5fa; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--wash); color:var(--ink); font:15px/1.5 system-ui,-apple-system,sans-serif; }}
    main {{ width:min(1180px,calc(100% - 32px)); margin:32px auto 72px; }} header {{ padding:34px; border-radius:24px; background:#17254c; color:#fff; }}
    h1 {{ margin:0 0 8px; font-size:clamp(2rem,5vw,3.6rem); letter-spacing:-.04em; }} h2 {{ margin:0 0 18px; font-size:1.4rem; }}
    header p {{ max-width:780px; margin:0; color:#d9e2ff; }} section {{ margin-top:24px; padding:26px; border:1px solid var(--line); border-radius:20px; background:var(--paper); }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:12px; margin-top:22px; }} .card {{ padding:16px; border-radius:14px; background:#f7f8fc; }}
    .card span {{ display:block; color:var(--muted); font-size:.8rem; text-transform:uppercase; letter-spacing:.08em; }} .card strong {{ display:block; margin-top:4px; font-size:1.7rem; }}
    .graph {{ overflow:auto; }} .graph svg {{ display:block; width:100%; height:auto; min-width:760px; }} .table-wrap {{ overflow:auto; }}
    table {{ width:100%; border-collapse:collapse; }} th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }} th {{ color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.05em; }}
    td:first-child {{ max-width:620px; overflow-wrap:anywhere; }} .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:24px; }} .grid section {{ margin:0; }}
    .empty,.note {{ color:var(--muted); }} code {{ padding:.1rem .35rem; border-radius:5px; background:#edf0f7; }} footer {{ margin-top:28px; color:var(--muted); }}
  </style>
</head>
<body>
<main>
  <header><h1>JourneyGraph</h1><p>Cross-trace graph analysis of recurring paths, transitions, loops, failures, and outcomes. Associations shown here are descriptive and do not establish causation.</p><div class="cards">{cards}</div></header>
  <section id="graph"><h2>Aggregate journey graph</h2><p class="note">Edge width represents observed adjacent-transition count.</p><div class="graph">{svg}</div></section>
  <section id="paths"><h2>Frequent paths</h2>{_table(("Path", "Traces", "Success rate", "Outcomes"), path_rows, "No paths available.")}</section>
  <section id="transitions"><h2>Frequent transitions</h2>{_table(("From", "To", "Weight", "Traces"), transition_rows, "No transitions available.")}</section>
  <div class="grid">
    <section id="retries"><h2>Retries</h2>{_table(("Category", "Occurrences", "Traces"), retry_rows, "No adjacent retries detected.")}</section>
    <section id="loops"><h2>Loops</h2>{_table(("Loop sequence", "Occurrences", "Traces"), loop_rows, "No return loops detected.")}</section>
    <section id="failures"><h2>Failure points</h2>{_table(("Category", "Error events", "Terminal failures", "Traces"), point_rows, "No failure points detected.")}</section>
    <section id="dropoffs"><h2>Drop-off points</h2>{_table(("Category", "Traces"), dropoff_rows, "No drop-off points detected.")}</section>
  </div>
  <section id="cohorts"><h2>Cohorts</h2>{_table(("Value", "Traces", "Success rate", "Outcomes"), cohort_rows, "No retained cohort values available.")}</section>
  <section id="metrics"><h2>Metrics</h2>{_table(("Metric", "Present", "Missing", "Total", "Mean", "P95"), metric_rows, "No metric summaries available.")}</section>
  <section id="quality"><h2>Data-quality and privacy warnings</h2>{_table(("Code", "Location", "Observation", "Correction"), warning_rows, "No warnings.")}</section>
  <section id="privacy"><h2>Privacy and sharing</h2><p>JourneyGraph excludes unknown and sensitive metadata by policy, but retained labels, identifiers, timestamps, cohorts, and rare paths may still be sensitive. Inspect this local file before sharing it. Redaction is not anonymization.</p></section>
  <script type="application/json" id="journeygraph-data">{embedded}</script>
  <footer>Generated locally by JourneyGraph {escape(str(report.get("tool_version", "0.1.0")))}. No trace data was transmitted.</footer>
</main>
</body>
</html>
"""
