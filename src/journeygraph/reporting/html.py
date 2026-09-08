"""Self-contained, escaped HTML analytical report."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html import escape

from journeygraph.reporting.serialize import serialize_embedded_analysis
from journeygraph.reporting.svg import render_svg


@dataclass(frozen=True)
class _MarkupCell:
    html: str
    css_class: str = ""


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
    if isinstance(value, _MarkupCell):
        return value.html
    return escape(_value(value), quote=True)


def _path_label(item: Mapping[str, object]) -> str:
    labels = item.get("labels", [])
    if isinstance(labels, Sequence) and not isinstance(labels, (str, bytes)):
        return " → ".join(str(label) for label in labels)
    return str(labels)


def _path_cell(item: Mapping[str, object]) -> _MarkupCell:
    raw_labels = item.get("labels", [])
    labels = (
        [str(label) for label in raw_labels]
        if isinstance(raw_labels, Sequence) and not isinstance(raw_labels, (str, bytes))
        else [str(raw_labels)]
    )
    if not labels:
        return _MarkupCell("—", "path-cell")
    full_label = " → ".join(labels)
    content = [f'<span class="path-step">{escape(labels[0])}</span>']
    content.extend(
        (
            '<span class="path-segment"><span class="path-arrow" aria-hidden="true">→</span>'
            f'<span class="path-step">{escape(label)}</span></span>'
        )
        for label in labels[1:]
    )
    return _MarkupCell(
        f'<span class="path-flow" aria-label="{escape(full_label, quote=True)}">'
        f"{''.join(content)}</span>",
        "path-cell",
    )


def _rate_cell(value: object) -> _MarkupCell:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        percent = float(value) * 100
        if 0 < percent < 0.1:
            rendered = "<0.1"
        elif 99.9 < percent < 100:
            rendered = ">99.9"
        else:
            rendered = f"{percent:.1f}".removesuffix(".0")
        return _MarkupCell(f'<span class="rate">{escape(rendered)}%</span>', "numeric-cell")
    return _MarkupCell(f'<span class="rate">{escape(_value(value))}</span>', "numeric-cell")


def _outcome_cell(value: object) -> _MarkupCell:
    if not isinstance(value, Mapping):
        return _MarkupCell(escape(_value(value)), "outcome-cell")
    values = {str(name): count for name, count in value.items()}
    preferred_order = ("success", "failure", "handoff", "dropoff", "unknown")
    names = [name for name in preferred_order if name in values]
    names.extend(sorted(name for name in values if name not in names))
    badges: list[str] = []
    for name in names:
        count = values[name]
        if _sort_number(count) <= 0:
            continue
        css_name = name if name in preferred_order else "other"
        label = name.replace("_", " ").title()
        badges.append(
            f'<span class="outcome outcome-{css_name}">{escape(label)} '
            f"<strong>{_cell(count)}</strong></span>"
        )
    return _MarkupCell(
        f'<span class="outcomes">{"".join(badges)}</span>' if badges else "—",
        "outcome-cell",
    )


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


def _table(
    label: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    empty: str,
) -> str:
    if not rows:
        return f'<p class="empty">{escape(empty)}</p>'
    head = "".join(f'<th scope="col">{escape(header)}</th>' for header in headers)
    rendered_rows: list[str] = []
    for row in rows:
        cells: list[str] = []
        for header, value in zip(headers, row, strict=True):
            css_class = value.css_class if isinstance(value, _MarkupCell) else ""
            if not css_class and isinstance(value, (int, float)) and not isinstance(value, bool):
                css_class = "numeric-cell"
            class_attribute = f' class="{css_class}"' if css_class else ""
            cells.append(
                f'<td data-label="{escape(header, quote=True)}"{class_attribute}>'
                f"{_cell(value)}</td>"
            )
        rendered_rows.append(f"<tr>{''.join(cells)}</tr>")
    body = "".join(rendered_rows)
    escaped_label = escape(label, quote=True)
    return (
        f'<div class="table-wrap" role="region" aria-label="{escaped_label} table" tabindex="0">'
        f'<table><caption class="sr-only">{escaped_label}</caption>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


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
        f'<div class="card"><dt>{escape(label)}</dt><dd class="card-value">{_cell(value)}</dd></div>'
        for label, value in (
            ("Traces", total_values.get("traces", 0)),
            ("Events", total_values.get("events", 0)),
            ("Success", outcome_values.get("success", 0)),
            ("Failure", outcome_values.get("failure", 0)),
            ("Handoff", outcome_values.get("handoff", 0)),
            ("Drop-off", outcome_values.get("dropoff", 0)),
            ("Unknown", outcome_values.get("unknown", 0)),
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
            _path_cell(path),
            path.get("count", 0),
            _rate_cell(path.get("success_rate", "—")),
            _outcome_cell(path.get("outcomes", {})),
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
            _rate_cell(_success_rate(cohort)),
            _outcome_cell(cohort.get("outcomes", {})),
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
    :root {{ color-scheme:light; --ink:#18213a; --muted:#59647d; --line:#dce1ed; --accent:#3256a8; --paper:#fff; --wash:#f3f5fa; --success:#176b4d; --failure:#a23b3b; --handoff:#6b4ba1; --dropoff:#8a5a12; }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; background:var(--wash); color:var(--ink); font:15px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; -webkit-font-smoothing:antialiased; }}
    main {{ width:min(1180px,calc(100% - 32px)); margin:32px auto 72px; }}
    main > * {{ min-width:0; }}
    .skip-link {{ position:fixed; z-index:10; top:12px; left:12px; padding:10px 14px; border-radius:10px; background:#fff; color:var(--accent); box-shadow:0 8px 24px #17254c33; transform:translateY(-160%); }}
    .skip-link:focus {{ transform:translateY(0); }}
    header {{ padding:36px; border-radius:24px; background:#17254c; color:#fff; box-shadow:0 14px 40px #17254c1f; }}
    h1 {{ margin:0 0 8px; font-size:clamp(2.25rem,5vw,3.5rem); line-height:1.05; letter-spacing:-.045em; }}
    h2 {{ margin:0 0 10px; font-size:clamp(1.2rem,2vw,1.42rem); line-height:1.25; letter-spacing:-.018em; }}
    header p {{ max-width:820px; margin:0; color:#d9e2ff; font-size:1rem; }}
    section {{ margin-top:24px; padding:28px; border:1px solid var(--line); border-radius:20px; background:var(--paper); box-shadow:0 6px 22px #17254c08; }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(126px,1fr)); gap:12px; margin:24px 0 0; }}
    .card {{ min-width:0; padding:16px; border:1px solid #ffffff99; border-radius:14px; background:#f7f8fc; }}
    .card dt {{ color:var(--muted); font-size:.78rem; font-weight:650; text-transform:uppercase; letter-spacing:.08em; }}
    .card-value {{ margin:3px 0 0; color:var(--ink); font-size:1.75rem; font-weight:750; line-height:1.2; font-variant-numeric:tabular-nums; }}
    .graph {{ overflow-x:auto; border:1px solid #e8ebf3; border-radius:16px; background:#f7f8fc; scrollbar-color:#aeb7cc transparent; scrollbar-width:thin; overscroll-behavior-inline:contain; }}
    .graph svg {{ display:block; width:100%; min-width:900px; height:auto; }}
    .scroll-hint {{ display:none; margin:10px 0 0; color:var(--muted); font-size:.85rem; }}
    .table-wrap {{ overflow-x:auto; scrollbar-color:#aeb7cc transparent; scrollbar-width:thin; }}
    table {{ width:100%; border-collapse:collapse; }}
    caption.sr-only,.sr-only {{ position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }}
    th,td {{ padding:12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-size:.76rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em; }}
    td {{ color:#26314d; }}
    tbody tr:last-child td {{ border-bottom:0; }}
    td:first-child {{ max-width:620px; overflow-wrap:break-word; }}
    .numeric-cell {{ font-variant-numeric:tabular-nums; }}
    .rate {{ white-space:nowrap; font-weight:700; color:#26314d; }}
    .path-flow {{ line-height:1.7; }}
    .path-step {{ display:inline-block; max-width:100%; overflow-wrap:anywhere; font-weight:560; }}
    .path-segment {{ display:inline; }}
    .path-arrow {{ display:inline-block; margin:0 .35rem; color:#7b86a0; }}
    .outcomes {{ display:flex; flex-wrap:wrap; gap:6px; }}
    .outcome {{ display:inline-flex; align-items:baseline; gap:5px; padding:3px 8px; border:1px solid #dce1ed; border-radius:999px; background:#f7f8fc; color:#46516b; font-size:.78rem; white-space:nowrap; }}
    .outcome-success {{ border-color:#b8dfd0; background:#eef8f4; color:var(--success); }}
    .outcome-failure {{ border-color:#ecc8c8; background:#fff3f3; color:var(--failure); }}
    .outcome-handoff {{ border-color:#d8cbea; background:#f7f2fc; color:var(--handoff); }}
    .outcome-dropoff {{ border-color:#ead6b7; background:#fff8ec; color:var(--dropoff); }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:24px; margin-top:24px; }}
    .grid section {{ min-width:0; margin:0; }}
    .empty,.note {{ color:var(--muted); }}
    .note {{ margin:0 0 16px; max-width:860px; }}
    code {{ padding:.1rem .35rem; border-radius:5px; background:#edf0f7; }}
    footer {{ margin-top:28px; color:var(--muted); font-size:.9rem; }}
    a:focus-visible,.graph:focus-visible,.table-wrap:focus-visible {{ outline:3px solid #7897df; outline-offset:3px; }}
    @media (max-width:700px) {{
      html {{ scroll-behavior:auto; }}
      main {{ width:min(1180px,calc(100% - 24px)); margin:12px auto 48px; }}
      header {{ padding:26px; border-radius:20px; }}
      header p {{ font-size:.94rem; }}
      section {{ margin-top:16px; padding:20px; border-radius:17px; }}
      .cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:20px; }}
      .card {{ padding:14px; }}
      .card-value {{ font-size:1.55rem; }}
      .graph svg {{ min-width:880px; }}
      .scroll-hint {{ display:block; }}
      .table-wrap {{ overflow:visible; }}
      table,tbody,tr,td {{ display:block; width:100%; }}
      thead {{ position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }}
      tbody {{ display:grid; gap:12px; }}
      tbody tr {{ padding:7px 14px; border:1px solid var(--line); border-radius:14px; background:#fbfcfe; }}
      td,td:first-child {{ display:grid; grid-template-columns:minmax(86px,.42fr) minmax(0,1fr); gap:12px; max-width:none; padding:9px 0; border:0; overflow-wrap:break-word; }}
      td + td {{ border-top:1px solid #e8ebf3; }}
      td::before {{ content:attr(data-label); color:var(--muted); font-size:.7rem; font-weight:700; text-transform:uppercase; letter-spacing:.05em; }}
      .outcomes {{ padding-top:1px; }}
      .grid {{ grid-template-columns:1fr; gap:16px; margin-top:16px; }}
    }}
    @media print {{
      body {{ background:#fff; }} main {{ width:100%; margin:0; }} header,section {{ box-shadow:none; break-inside:avoid; }}
      .graph {{ overflow:visible; }} .graph svg {{ min-width:0; }} .scroll-hint {{ display:none; }}
    }}
  </style>
</head>
<body>
<a class="skip-link" href="#report-content">Skip to report content</a>
<main id="report-content">
  <header><h1>JourneyGraph</h1><p>Cross-trace analysis of chronological paths, adjacency transitions, adjacent repetitions, return sequences, error events, and explicit outcomes. Associations shown here are descriptive and do not establish causation.</p><dl class="cards" aria-label="Analysis summary">{cards}</dl></header>
  <section id="graph"><h2>Aggregate chronological-adjacency graph</h2><p class="note">Edge width represents observed chronological adjacency. For OTLP spans, adjacency does not establish parent-aware control flow.</p><div class="graph" role="region" aria-label="Scrollable aggregate graph" tabindex="0" aria-describedby="graph-scroll-hint">{svg}</div><p class="scroll-hint" id="graph-scroll-hint">Scroll horizontally to inspect the complete graph.</p></section>
  <section id="paths"><h2>Chronological paths</h2>{_table("Chronological paths", ("Path", "Traces", "Success rate", "Outcomes"), path_rows, "No paths available.")}</section>
  <section id="transitions"><h2>Chronological adjacency transitions</h2>{_table("Chronological adjacency transitions", ("From", "To", "Weight", "Traces"), transition_rows, "No transitions available.")}</section>
  <div class="grid">
    <section id="retries"><h2>Adjacent repetitions</h2>{_table("Adjacent repetitions", ("Category", "Occurrences", "Traces"), retry_rows, "No adjacent repetitions detected.")}</section>
    <section id="loops"><h2>Return sequences</h2>{_table("Return sequences", ("Return sequence", "Occurrences", "Traces"), loop_rows, "No return sequences detected.")}</section>
    <section id="failures"><h2>Error and explicit-failure points</h2>{_table("Error and explicit-failure points", ("Category", "Error events", "Terminal failures", "Traces"), point_rows, "No error or explicit-failure points detected.")}</section>
    <section id="dropoffs"><h2>Drop-off points</h2>{_table("Drop-off points", ("Category", "Traces"), dropoff_rows, "No drop-off points detected.")}</section>
  </div>
  <section id="cohorts"><h2>Cohorts</h2>{_table("Cohorts", ("Value", "Traces", "Success rate", "Outcomes"), cohort_rows, "No retained cohort values available.")}</section>
  <section id="metrics"><h2>Metrics</h2>{_table("Metrics", ("Metric", "Present", "Missing", "Total", "Mean", "P95"), metric_rows, "No metric summaries available.")}</section>
  <section id="quality"><h2>Data-quality and privacy warnings</h2>{_table("Data-quality and privacy warnings", ("Code", "Location", "Observation", "Correction"), warning_rows, "No warnings.")}</section>
  <section id="privacy"><h2>Privacy and sharing</h2><p>JourneyGraph excludes unknown and sensitive metadata by policy, but retained labels, identifiers, timestamps, cohorts, and rare paths may still be sensitive. Inspect this local file before sharing it. Redaction is not anonymization.</p></section>
  <script type="application/json" id="journeygraph-data">{embedded}</script>
  <footer>Generated locally by JourneyGraph {escape(str(report.get("tool_version", "0.1.0")))}. No trace data was transmitted.</footer>
</main>
</body>
</html>
"""
