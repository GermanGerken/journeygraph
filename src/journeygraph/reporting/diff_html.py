"""Static, escaped HTML rendering of a ``journeygraph.diff`` payload."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape

from journeygraph.reporting.html import _table
from journeygraph.reporting.serialize import serialize_embedded_analysis


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _items(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _percent(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{value:.0%}"


def _points(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{value * 100:+.0f} pp"


def _number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{value:,.6g}"


def _relative(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{value:+.0%}"


def _size(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return abs(float(value))


def render_diff_html(diff: Mapping[str, object]) -> str:
    """Render a local comparison report with no executable script or remote dependency."""

    totals = _mapping(diff.get("totals"))
    base_totals, cand_totals = _mapping(totals.get("baseline")), _mapping(totals.get("candidate"))
    outcomes = _mapping(diff.get("outcomes"))
    success = _mapping(outcomes.get("known_success"))
    interval = _mapping(success.get("interval"))
    interval_text = (
        f"{_points(interval.get('low'))} to {_points(interval.get('high'))}" if interval else "—"
    )

    change_rows = [
        (change.get("statement", ""), str(change.get("kind", "")).replace("_", " "))
        for change in _items(diff.get("changes"))
    ]
    outcome_rows = [
        (
            outcome,
            _percent(_mapping(values).get("baseline")),
            _percent(_mapping(values).get("candidate")),
            _points(_mapping(values).get("delta")),
        )
        for outcome, values in _mapping(outcomes.get("rates")).items()
    ]
    categories = sorted(
        _items(diff.get("categories")),
        key=lambda item: (
            -_size(item.get("trace_share_delta"))
            if item.get("status") == "common"
            else -_size(_mapping(item.get("candidate") or item.get("baseline")).get("trace_share")),
            str(item.get("node_id")),
        ),
    )
    category_rows = [
        (
            item.get("label", ""),
            item.get("status", ""),
            _percent(_mapping(item.get("baseline")).get("trace_share")),
            _percent(_mapping(item.get("candidate")).get("trace_share")),
            _percent(_mapping(item.get("baseline")).get("error_rate")),
            _percent(_mapping(item.get("candidate")).get("error_rate")),
            _percent(_mapping(item.get("baseline")).get("known_success_rate")),
            _percent(_mapping(item.get("candidate")).get("known_success_rate")),
        )
        for item in categories
    ]
    variants = sorted(
        _items(diff.get("variants")),
        key=lambda item: (-_size(item.get("share_delta")), str(item.get("variant_id"))),
    )[:25]
    variant_rows = [
        (
            item.get("label", ""),
            item.get("status", ""),
            _percent(item.get("baseline_share")),
            _percent(item.get("candidate_share")),
            _points(item.get("share_delta")),
        )
        for item in variants
    ]
    metric_rows = [
        (
            name.replace("_", " "),
            _number(_mapping(values).get("baseline")),
            _number(_mapping(values).get("candidate")),
            _relative(_mapping(values).get("relative_delta")),
        )
        for name, values in _mapping(diff.get("metrics")).items()
        if name != "present_counts"
    ]
    cards = "".join(
        f'<article class="card"><span>{escape(label)}</span><strong>{escape(value)}</strong></article>'
        for label, value in (
            ("Baseline traces", str(base_totals.get("traces", 0))),
            ("Candidate traces", str(cand_totals.get("traces", 0))),
            ("Baseline success", _percent(success.get("baseline"))),
            ("Candidate success", _percent(success.get("candidate"))),
            ("Change", _points(success.get("delta"))),
        )
    )
    embedded = serialize_embedded_analysis(diff)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
  <title>JourneyGraph comparison report</title>
  <style>
    :root {{ color-scheme: light; --ink:#18213a; --muted:#59647d; --line:#dce1ed; --paper:#fff; --wash:#f3f5fa; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--wash); color:var(--ink); font:15px/1.5 system-ui,-apple-system,sans-serif; }}
    main {{ width:min(1180px,calc(100% - 32px)); margin:32px auto 72px; }} header {{ padding:34px; border-radius:24px; background:#17254c; color:#fff; }}
    h1 {{ margin:0 0 8px; font-size:clamp(2rem,5vw,3.2rem); letter-spacing:-.04em; }} h2 {{ margin:0 0 18px; font-size:1.4rem; }}
    header p {{ max-width:780px; margin:0; color:#d9e2ff; }} section {{ margin-top:24px; padding:26px; border:1px solid var(--line); border-radius:20px; background:var(--paper); }}
    .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:12px; margin-top:22px; }} .card {{ padding:16px; border-radius:14px; background:#f7f8fc; color:var(--ink); }}
    .card span {{ display:block; color:var(--muted); font-size:.8rem; text-transform:uppercase; letter-spacing:.08em; }} .card strong {{ display:block; margin-top:4px; font-size:1.5rem; }}
    .table-wrap {{ overflow:auto; }} table {{ width:100%; border-collapse:collapse; }} th,td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ color:var(--muted); font-size:.78rem; text-transform:uppercase; letter-spacing:.05em; }} td:first-child {{ max-width:620px; overflow-wrap:anywhere; }}
    .empty,.note {{ color:var(--muted); }} footer {{ margin-top:28px; color:var(--muted); }}
  </style>
</head>
<body>
<main>
  <header><h1>JourneyGraph comparison</h1><p>Observed differences between a baseline and a candidate export. Differences between two samples are descriptive; they do not establish what caused them.</p><div class="cards">{cards}</div></header>
  <section id="changes"><h2>Notable changes</h2><p class="note">Change in success among known outcomes: {escape(_points(success.get("delta")))} (95% Newcombe interval {escape(interval_text)}).</p>{_table(("Change", "Kind"), change_rows, "No change met the thresholds and minimum support.")}</section>
  <section id="outcomes"><h2>Outcomes</h2>{_table(("Outcome", "Baseline", "Candidate", "Change"), outcome_rows, "No outcomes available.")}</section>
  <section id="categories"><h2>Operation categories</h2>{_table(("Category", "Status", "Baseline traces", "Candidate traces", "Baseline errors", "Candidate errors", "Baseline success", "Candidate success"), category_rows, "No categories available.")}</section>
  <section id="variants"><h2>Path variants</h2>{_table(("Variant", "Status", "Baseline share", "Candidate share", "Change"), variant_rows, "No path variants available.")}</section>
  <section id="metrics"><h2>Metrics</h2>{_table(("Metric", "Baseline", "Candidate", "Relative change"), metric_rows, "No metrics available.")}</section>
  <script type="application/json" id="journeygraph-diff">{embedded}</script>
  <footer>Generated locally by JourneyGraph. No trace data was transmitted.</footer>
</main>
</body>
</html>
"""
