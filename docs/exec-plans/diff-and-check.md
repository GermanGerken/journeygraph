# Diff and Check ExecPlan

This living plan implements Stage 3 of the product roadmap: answer "what changed after the
release?" and let teams gate CI or evaluation runs on journey-level rules. It adds a
`journeygraph diff` command that compares two exports and a `journeygraph check` command that
evaluates declarative thresholds. It reuses the existing analysis payload (schema 1.2) and does
not change ingestion, normalization, identities, or the privacy boundary.

Status: **implemented on `feat/diff-check` (stacked on `feat/path-variants`); awaiting
review.** The owner asked on 2026-11-08 to continue the roadmap autonomously within a bounded
session, which this plan records as its approval.

## Purpose and observable outcome

The north-star scenario is: "I shipped a new agent version. Show me in two minutes which paths
became more common, where retries, errors, or cost grew, and which steps are associated with
failures." Today a user must run two analyses and compare JSON by hand.

After this plan:

- `journeygraph diff BASELINE CANDIDATE --output-dir DIR` writes `diff.json` and a static
  `diff.html` comparing outcomes, categories, transitions, path variants, and metrics, plus a
  ranked list of notable changes;
- `journeygraph check INPUT --rules rules.toml [--baseline BASELINE]` evaluates absolute
  thresholds and, with a baseline, regression limits; it prints one line per rule, can write a
  Markdown summary (for example to `$GITHUB_STEP_SUMMARY`), and exits with code `5` when any
  rule fails.

## Scope and non-goals

In scope: a pure `journeygraph.analytics.compare` module, a pure `journeygraph.analytics.rules`
module, the two commands, a static diff renderer, documentation, and tests.

Out of scope: a hosted service, a GitHub Action package (the Markdown summary makes a workflow
step trivial; a packaged Action can follow), statistical significance testing beyond reported
intervals, graph-diff SVG, and releases.

## Contract decisions

### Comparison payload (`journeygraph.diff`, `diff_schema_version: "1.0"`)

`compare_analyses(baseline, candidate, min_support)` consumes two analysis payloads and returns:

- `config`: `min_support` and both payloads' `schema_version`.
- `totals`: baseline and candidate trace and event counts.
- `outcomes`: per outcome, baseline rate, candidate rate, and delta; plus `known_success`:
  success among known outcomes for both sides, the delta, and a 95% Newcombe hybrid score
  interval for the difference (`candidate - baseline`), built from Wilson intervals.
- `categories`: the union of node IDs with `status` (`added`, `removed`, `common`), and for each
  side the trace share (`trace_count / traces`), error-event rate, p95 duration, and
  known-outcome success among visiting traces, with deltas where both sides exist.
- `transitions`: the union of `(source, target)` with status and trace shares.
- `variants`: the union of variant IDs with status, labels, and trace shares.
- `metrics`: mean cost per trace, mean total tokens per trace, and global p50/p95 duration for
  both sides with absolute and relative deltas (`null` when undefined).
- `changes`: at most 15 ranked notable changes (below).

Lists are ordered by identity; rates use the existing 12-digit rounding.

### Notable changes

| Kind | Emitted when |
| --- | --- |
| `success_rate_change` | Known-outcome success differs by at least 0.05 and both sides have at least `min_support` known outcomes. |
| `category_added` / `category_removed` | A category appears only on one side in at least `min_support` traces. |
| `category_share_change` | A common category's trace share changes by at least 0.10, with at least `min_support` traces on one side. |
| `category_error_rate_change` | A common category's error-event rate changes by at least 0.10, with at least `min_support` events on both sides. |
| `variant_share_change` | A variant's trace share changes by at least 0.10 (including new or vanished variants), with at least `min_support` traces on one side. |
| `cost_per_trace_change`, `duration_p95_change` | The relative change is at least 20% and both sides have at least `min_support` present values. |

Ranking: kind order as listed, then absolute effect descending, then identity. Statements are
fixed English templates and describe observed differences between two samples, never causes.

### Rules (`check`)

Rules are TOML, parsed with the standard-library `tomllib`:

```toml
[thresholds]
min_success_rate = 0.8          # success among known outcomes
max_failure_rate = 0.1          # failure among known outcomes
max_unknown_rate = 0.5          # unknown among all traces
max_error_event_rate = 0.05     # error events among all events
max_mean_cost_per_trace = 0.05  # supplied cost; fails when no cost is present
max_p95_duration_ms = 5000      # global event p95

[regressions]                    # requires --baseline
max_success_rate_drop = 0.05
max_error_event_rate_increase = 0.02
max_mean_cost_per_trace_increase = 0.25   # relative
forbid_new_categories = true
```

Unknown tables or keys, wrong types, and `[regressions]` without `--baseline` are usage errors
(exit code `2`). Each rule reports `name`, `passed`, `observed`, `limit`, and a message. Rules
are evaluated in a fixed order and only from analysis payloads, so a stored `analysis.json`
could be checked the same way. A per-trace retry rule was considered and deferred: the payload
reports retries per category, and traces with retries in several categories cannot be
de-duplicated from it.

Exit codes: `0` all rules passed, `5` at least one rule failed; existing codes are unchanged.
`--summary-md PATH` writes (or with `--force` replaces) a Markdown table; `-` is not
supported, to keep file semantics explicit.

## Test strategy

- Unit: comparison of hand-built payloads (added/removed/common, shares, deltas, Newcombe
  interval against a published example, change thresholds and ranking, missing metrics);
  rule parsing errors and each rule at, below, and above its limit.
- Functional (installed CLI): `diff` on two fixtures with hand-computed changes and byte-stable
  artifacts; `check` passing, failing (exit 5), regression rules with a baseline, Markdown
  summary, and usage errors.

## Acceptance criteria

- [x] `diff` writes `diff.json` and `diff.html` with the documented content; HTML is static and
  escaped with the same CSP as `report.html`.
- [x] `check` evaluates thresholds and regressions with exit codes 0, 2, and 5.
- [x] `make verify` passes with coverage at or above 90%.
- [x] README, CLI, architecture docs, and changelog are updated.

## Progress

- [x] 2026-11-08: Branched `feat/diff-check` from `feat/path-variants`.
- [x] Comparison, notable changes, rules, both commands, renderer, docs, tests.

## Decision log

- **Compare payloads, not datasets.** `diff` analyzes both inputs with the same options and
  compares the resulting payloads, so a stored `analysis.json` can be compared later by the API.
- **Newcombe interval for the success-rate difference.** It is well defined for small samples
  and rates of 0 or 1, matching the existing Wilson intervals.
- **New exit code 5 for failed checks.** Distinguishes "the data violates your rules" from
  invalid input (2) or I/O problems (3).

## Outcomes and retrospective

Verification on macOS with Python 3.12 on 2026-11-08: `make verify` passed with 403 tests
(9 intentionally rejected fixtures skipped) and 95.60% combined branch-aware coverage, plus
Ruff, mypy, wheel smoke, documentation, corpus, dependency audit, Bandit, and secret scanning.
The Newcombe implementation reproduces the published 56/70 versus 48/80 example. On the new
release fixtures, `diff` reports seven hand-computed changes; the 95% interval for the -30
point success change still includes zero at 10 traces per side, which the report shows.

`make mutation` (unit and integration tests): killed mutants `compare.py` 868 of 1,178
(73.7%) and `rules.py` 336 of 396 (84.8%). Most `compare.py` survivors change statement text
or the ordering of equal-effect changes, which the functional tests check only through the
CLI, which mutation runs do not execute.

Follow-ups: a packaged GitHub Action around `check`, a graph-diff SVG, and tighter unit
oracles for change statements.
