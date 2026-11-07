# Readable Report ExecPlan

This living plan implements Stage 1 of the product roadmap: make the generated report answer
"where should I look?" instead of only "what was counted?". It adds per-node and per-transition
statistics, a small set of deterministic ranked findings, and a layered, outcome-colored graph
layout. It does not change ingestion, normalization, outcome reconciliation, stable identities,
or the privacy boundary.

Status: **implemented on `feat/readable-report`; awaiting review.** Approved by the owner on
2026-11-08 with the proposed defaults (`min_support` 3, no demo change, 60-category cap).

## Purpose and observable outcome

On `origin/main` at `017e4f2` (v0.1.2 plus the instrumented-trace harness), the report has three
user-facing weaknesses:

1. `graph.svg` places nodes on an ellipse in SHA-256 ID order. Flow direction is invisible,
   edges cross the whole canvas, and nothing distinguishes healthy from problematic steps.
2. A node carries only `event_count` and `trace_count`; a transition only `weight` and
   `trace_count`. Duration, tokens, cost, error status, and outcomes exist only as global
   summaries, so the report cannot show where time, cost, or non-success concentrate.
3. The HTML report is a sequence of tables. The user must discover every pattern manually.

After this plan:

- every node in `analysis.json` includes its error-event count, duration/token/cost summaries,
  and the outcome distribution of traces that visit it;
- every transition includes the outcome distribution of traces that contain it;
- a new top-level `findings` section lists at most ten ranked, explainable observations, each
  with its support, baseline, Wilson interval, and an association-only statement;
- `graph.svg` uses a deterministic layered left-to-right layout, colors nodes by error rate and
  edges by success rate among known outcomes, draws return edges distinctly, and includes a
  text legend;
- `report.html` opens with a "Key findings" section and a per-node table;
- identical accepted input and configuration still produce byte-identical artifacts.

## Scope and non-goals

In scope: `journeygraph.analytics` (node/edge statistics, findings), a new pure
`journeygraph.reporting.layout` module, `reporting/svg.py`, `reporting/html.py`, the analysis
schema, one CLI option, tests, documentation, the README image, and the changelog.

Out of scope: path variants or retry collapsing (Stage 2), filters and configurable node keys
(Stage 2), `diff`/`check` (Stage 3), new importers, parent-aware OTLP analysis, Sankey diagrams,
interactive JavaScript, a package release, and changes to the packaged demo dataset. A version
bump, tag, or publication needs its normal release authorization.

## Contract decisions

### Analysis schema 1.1 (additive)

`analysis-v1.schema.json` uses `additionalProperties: false`, so any new field is a schema
change. The plan bumps `schema_version` from `"1.0"` to `"1.1"`:

- all existing keys, meanings, sort orders, and identities stay unchanged;
- new fields are added to `node` and `transition`, and a new required top-level `findings`;
- the schema file keeps its name and `$id` and describes exactly `1.1`;
- the changelog carries migration guidance: strict validators pinned to the 1.0 schema must
  update; readers that ignore unknown fields need no change.

Considered and rejected: separate top-level `node_metrics` arrays (duplicates identity joins for
every consumer) and keeping `1.0` (would silently invalidate strict 1.0 validators).

### Per-node statistics

Added to each `nodes[]` item:

| Field | Definition |
| --- | --- |
| `error_event_count` | Events of this category with `status: error`. |
| `metrics` | `metricSummary` for `duration_ms`, `total_tokens`, `cost_usd` over this category's events, using the existing nearest-rank `summarize_metric`. |
| `trace_outcomes` | `outcomeSummary` over distinct traces that contain at least one event of this category. Rates use `trace_count` as the denominator, matching existing outcome payloads. |

### Per-transition statistics

Added to each `transitions[]` item: `trace_outcomes`, the `outcomeSummary` over distinct traces
containing the transition at least once.

### Known-outcome rates

Since v0.1.2 a missing business outcome is `unknown`. Every success-rate comparison in findings
and every color derived from success uses **known-outcome traces only** (all outcomes except
`unknown`) as the denominator and reports the excluded unknown count explicitly. If no known
outcomes exist, outcome-based findings and edge coloring are omitted and the legend says so.

### Findings

`findings` is an object `{ "config": {...}, "items": [...] }`. `config` records `min_support`
(default `3`, CLI `--min-support N`, `N >= 1`) and `max_items` (fixed at `10`). Each item has
`kind`, `node_id`, `label`, `support`, `baseline_support` (or `null`), `value`, `baseline` (or
`null`), `effect` (the ranking magnitude), `interval` (`{"method":"wilson","level":0.95,
"low":…,"high":…}` or `null`), `support_level` (`"low"` when `support` or `baseline_support`
is below 10, else `"normal"`), and a deterministic English `statement` built from a fixed
template. All five kinds are about a single category, so a plain `node_id` replaced the
originally sketched `subject`/`labels` pair.

Kinds, all purely descriptive:

1. `outcome_association` — for a node visited by at least `min_support` known-outcome traces
   while at least `min_support` known-outcome traces do not visit it: success rate among visiting
   traces versus non-visiting traces. Emitted when the absolute difference is at least `0.20`.
   Template: "Traces that include X had a success rate of A (n=…) versus B (n=…) for traces
   that do not. This is an association, not a cause."
2. `error_hotspot` — node with at least `min_support` events and an error-event rate of at least
   `0.20`; the baseline is the dataset-wide error-event rate.
3. `duration_concentration` — node whose summed `duration_ms` is at least `0.25` of the dataset
   sum. For datasets carrying the `otlp_chronological_adjacency` warning, nested spans overlap,
   so the statement says "share of summed span durations, not wall-clock time".
4. `cost_concentration` — the same rule over present `cost_usd`, emitted only when at least
   `min_support` events have cost; the missing count is stated.
5. `retry_prevalence` — node whose adjacent retries (existing `retries` definition) appear in at
   least `0.10` of traces and in at least `min_support` traces.

Ranking: by kind priority (1, 2, 3, 4, 5), then absolute effect (difference, rate, or share)
descending, then support descending, then subject ID ascending. Values are rounded with the
existing `_rate` precision before ranking so float noise cannot reorder ties. The first
`max_items` are published; `items` may be empty.

Thresholds are fixed constants in this plan, documented in `docs/schema.md`, and exposed only
through `min_support`. Making the others configurable is deferred until real usage justifies it.

### Layered layout (presentation only)

The layout is computed in a new pure module `journeygraph.reporting.layout` from the analysis
payload. It is **not** serialized into `analysis.json`: layout is presentation, and keeping it
out preserves the "reporting does not recalculate analytics" rule in reverse.

1. **Node cap.** If there are more than 60 nodes, keep the 60 with the highest `trace_count`
   (ties by ID) and print "N categories hidden" in the SVG legend.
2. **Cycle breaking.** Depth-first search starting from entry nodes ordered by entry count
   descending, then ID; remaining unvisited nodes in ID order. Edges to a node on the current
   DFS stack are marked as return edges. Self-transitions are drawn as self-loops.
3. **Layering.** Longest-path layering on the resulting acyclic graph; layer 0 holds sources.
4. **Ordering.** Initial order within a layer by `trace_count` descending, then ID. Then eight
   alternating downward/upward barycenter sweeps using exact `fractions.Fraction` positions;
   ties keep the previous order. No randomness and no float comparisons in ordering.
5. **Long edges.** Forward edges spanning more than one layer are split through virtual slots
   that take part in ordering, so they route around intermediate categories (added during
   implementation after the first render drew `model → validation` through `ticket_lookup`).
6. **Coordinates.** Fixed horizontal layer spacing and vertical slot spacing; the canvas grows
   with layer count and the largest layer. Forward edges are cubic Béziers from the right edge
   of the source to the left edge of the target; return edges arc below the nodes in a dashed
   style; self-loops sit above the node.

### Visual encoding

- Node border/fill: four buckets of error-event rate (`0`, `<0.1`, `<0.3`, `>=0.3`) with a
  sequential palette that keeps WCAG AA text contrast. Bucket boundaries appear in the legend.
- Edge stroke color: three buckets of known-outcome success rate among traces containing the
  edge; gray when it has no known outcomes. Stroke width keeps the existing logarithmic weight.
- Color is never the only channel: every node and edge `<title>` states the exact rates and
  counts, and the legend is plain SVG text.
- SVG safety rules stay: no scripts, `foreignObject`, event handlers, links, or remote
  resources; all labels escaped.

### HTML report

- New first section "Key findings": an ordered list of `statement` values plus support,
  baseline, and interval columns; an explicit empty state ("No observation met the minimum
  support of N traces"); a fixed note that findings are associations.
- New "Operation categories" table: label, traces, events, error rate, p50/p95 duration,
  summed cost, known-outcome success rate, unknown count. Sorted by trace count, then ID.
- Unchanged CSP: `default-src 'none'; style-src 'unsafe-inline'; img-src data:`. No JavaScript.

### CLI and API

- `journeygraph analyze --min-support N` (default 3). `demo` uses the default.
- `analyze_file`/`analyze_dataset` gain a keyword-only `min_support: int = 3`. The CLI rejects
  non-positive or non-integer values as an `argparse` usage error (exit code 2, no artifacts).
  The pure API raises `ValueError`, because `ValidationError` describes input records.

## Milestones

1. **Baseline.** Branch `feat/readable-report` from `main`. Run `make verify` and record test
   count, coverage, and `make benchmark` timings in this plan.
2. **Node and transition statistics.** Extend `GraphNode`/`GraphEdge` payload assembly in
   analytics (graph construction stays identity-only), bump the schema to 1.1, update
   `scripts/check_docs.py` expectations and `docs/schema.md`.
3. **Findings.** Implement `journeygraph.analytics.findings` as a pure module with a
   self-contained Wilson-interval helper; wire `min_support` through API and CLI.
4. **Layout and SVG.** Implement `journeygraph.reporting.layout`; rewrite the SVG renderer on
   top of it with the encoding and legend above.
5. **HTML.** Add the findings and category sections; keep every existing section.
6. **Documentation and evidence.** Regenerate `docs/assets/demo-graph.svg`, update README
   numbers and screenshots, `docs/architecture.md`, `docs/cli.md`, `CHANGELOG.md`; add the new
   modules to `[tool.mutmut] only_mutate`; run `make verify`, `make mutation`, `make benchmark`.

## Test strategy

Tests are written before each milestone's production change, following AGENTS.md.

- **Functional (installed CLI, real files).** New fixture `findings_association.jsonl` with
  about 30 hand-designed traces where one tool is visited by mostly failing traces, one node
  has a high error rate, one dominates duration, and some traces lack outcomes. Assert the exact
  `findings.items` kinds, order, support, and values computed by hand in the test oracle;
  `--min-support 50` yields an empty list and the HTML empty state; `--min-support 0` exits 2.
- **Unit.** Wilson interval against published reference values; per-node outcome counts and
  unknown exclusion; each finding kind at, just below, and just above its threshold; ranking
  ties; OTLP duration wording; node-cap behavior; cycle breaking on retries, loops, and
  disconnected components.
- **Layout invariants (Hypothesis).** For generated graphs: no two node rectangles overlap;
  every non-return edge goes strictly left to right; every node appears exactly once; output is
  identical under permutation of input node and edge order.
- **Determinism.** Analyzing permuted copies of the same fixture produces byte-identical
  `analysis.json`, `graph.svg`, and `report.html`.
- **Safety.** Extend the hostile-label SVG/HTML tests to cover legend text, finding statements,
  and the category table.
- **Schema.** Every generated payload (demo, fixtures, OTLP integration corpus) validates
  against the 1.1 schema.
- **Performance.** `make benchmark` records layout and findings time on the 2,000-trace scenario;
  the plan records the number but makes no general performance claim.

## Acceptance criteria

- [ ] `analysis.json` reports `schema_version: "1.1"` and validates against the updated schema.
- [ ] All 1.0 keys, identities, and orderings are unchanged (existing tests pass unmodified
  except for the schema version constant).
- [ ] Nodes and transitions include the statistics defined above, with unknown outcomes
  excluded from success comparisons and reported explicitly.
- [ ] `findings` follows the definitions, thresholds, ranking, and cap; statements contain no
  causal language.
- [ ] The SVG uses the layered layout, visual encoding, and legend; existing SVG safety tests
  and the new invariants pass.
- [ ] The HTML report opens with Key findings and includes the category table; no JavaScript.
- [ ] Artifacts are byte-identical across input permutations.
- [ ] `make verify` passes with coverage at or above 90%; mutation score for new modules is
  recorded.
- [ ] README image, schema, CLI, architecture docs, and changelog are updated.

## Open questions for the owner

1. Default `min_support` of 3 favors visibility on small datasets; 5 is safer against noise.
   The plan proposes 3 with the `support_level: "low"` marker.
2. The packaged demo has 9 traces, so it will show few findings. Enlarging the demo changes
   README numbers and is excluded here; it could be a small follow-up.
3. Is the 60-node cap acceptable for the static SVG, with the full list kept in the table?

## Progress

- [x] 2026-11-08: Re-read README, product brief, architecture, AGENTS.md, the semantic-safety
  plan, the analysis schema, analytics, graph models, and reporting on `main` at `017e4f2`.
  Confirmed the demo produces 9 unique paths, 2 unknown outcomes, and an ID-ordered ellipse
  layout.
- [x] 2026-11-08: Owner approved the plan and the proposed defaults.
- [x] Milestone 1: branch `feat/readable-report`; baseline `make verify` passed with 270 tests
  and 93.32% coverage; `make benchmark` end-to-end 6.15 s (analysis 1.50 s, reporting 0.016 s).
- [x] Milestone 2: per-node and per-transition statistics, schema 1.1, contract updates in
  `scripts/check_docs.py`, `scripts/verify_wheel.py`, and existing contract tests.
- [x] Milestone 3: `journeygraph.analytics.findings`, Wilson helper, `--min-support`.
- [x] Milestone 4: `journeygraph.reporting.layout` and the rewritten SVG renderer.
- [x] Milestone 5: Key findings and Operation categories sections in the HTML report.
- [x] Milestone 6: README (including stale 0.1.2 demo outcome counts), schema, CLI,
  architecture, changelog, regenerated `docs/assets/demo-graph.svg`, mutmut paths.

## Decision log

- **Additive 1.1 instead of a parallel schema.** One schema, one version bump, explicit
  migration note.
- **Layout is not analysis.** Positions stay out of `analysis.json`; layout is a pure reporting
  function of the payload.
- **Known outcomes only for success comparisons.** Treating `unknown` as non-success would
  reintroduce the inference removed in v0.1.2.
- **Fixed thresholds, one knob.** Only `min_support` is configurable until evidence shows which
  other thresholds users need.
- **Exact arithmetic in layout ordering.** `Fraction` barycenters avoid platform-dependent float
  ties and keep SVG output byte-stable on Windows and POSIX.
- **Sankey deferred.** The layered graph already shows flow; a second chart can follow if users
  ask for it.
- **Virtual slots for long edges.** Added during implementation; the invariant tests check that
  waypoints lie strictly between the source and target layers.
- **ASCII legend ranges.** Legend and interval text use "10% to 30%" rather than an en dash to
  satisfy the repository's Ruff `RUF001` rule.

## Outcomes and retrospective

Verification on macOS with Python 3.12 on 2026-11-08:

- `make verify` passed: 332 tests passed and 9 intentionally rejected fixtures skipped in the
  schema sweep, 94.68% combined branch-aware coverage (baseline 93.32%), plus Ruff, mypy,
  wheel smoke, documentation, corpus, dependency audit, Bandit, and secret scanning.
- `make benchmark` (2,000 traces, 24,000 events): end-to-end 6.50 s versus 6.15 s baseline;
  analysis including graph 1.62 s versus 1.50 s; reporting 0.024 s versus 0.016 s. This is one
  local run, not a general performance claim.
- `make mutation` had been failing on `main` since the instrumented-trace harness: mutmut's
  clean run could not find `test-data/pins.json` or `tests_functional/fixtures/`. Both are now
  in `[tool.mutmut] also_copy`. Killed mutants: `findings.py` 495 of 590 (83.9%),
  `layout.py` 331 of 439 (75.4%), `analyzer.py` 677 of 731 (92.6%). Survivors in the new
  modules are mostly defensive payload coercion and layout constants that do not change
  invariants; tightening them is left to a follow-up.
- The packaged demo now shows 4 findings and a layered graph. Artifacts are byte-identical
  when traces are reordered (functional test).

Known limitations: return transitions are drawn as arcs below the graph and can pass behind
intermediate categories; Native Windows CI evidence arrives when the branch is pushed.
