# Path Variants and Filters ExecPlan

This living plan implements the core of Stage 2 of the product roadmap: make recurring behavior
visible when exact paths are all unique. It adds explainable path variants, recurring short
sequences with their outcome associations, and trace filters. It builds on the readable-report
plan (analysis schema 1.1) and does not change ingestion, normalization, stable node or path
identities, outcome reconciliation, or the privacy boundary.

Status: **implemented on `feat/path-variants` (stacked on `feat/readable-report`); awaiting
review.** The owner asked on 2026-11-08 to continue the roadmap autonomously within a bounded
session, which this plan records as its approval.

## Purpose and observable outcome

Exact path grouping is too strict for agent traces. In the packaged demo all 9 traces have
unique exact paths; on real agents retries and repeated tool loops make nearly every trace
unique, so the "Chronological paths" table becomes a list of singletons.

After this plan:

- `path_variants` groups traces whose paths are equal after collapsing consecutive repeated
  blocks (for example `A B B B C` and `A B C` share the variant `A B+ C`, and `A (B C) (B C) D`
  becomes `A (B C)+ D`); each variant lists the exact path IDs it merged;
- `sequence_patterns` lists recurring contiguous category sequences of length 2 and 3 with the
  outcomes of the traces that contain them;
- a new finding kind, `sequence_association`, reports sequences whose containing traces differ
  in known-outcome success rate by at least 0.20;
- `journeygraph analyze` accepts `--outcome`, `--since`, and `--until` trace filters, and the
  payload records the filters and how many traces they excluded;
- the HTML report shows path variants and recurring sequences before exact paths.

## Scope and non-goals

In scope: a pure `journeygraph.analytics.variants` module, findings, filters in the API and
CLI, schema 1.2, HTML, tests, documentation, and the changelog.

Out of scope: configurable node keys (they change node identity and need their own plan),
deterministic sampling, fuzzy or edit-distance clustering, prefix trees, `diff`/`check`, new
importers, and releases.

## Contract decisions

### Analysis schema 1.2 (additive)

`schema_version` becomes `"1.2"`. New required top-level sections are `path_variants`,
`sequence_patterns`, and `filters`; `findings.items[].kind` gains `sequence_association`, and
such items carry `labels` (the sequence) in addition to `label`. Every 1.1 key, identity, and
ordering is unchanged.

### Path variants

The variant of a trace is computed from its exact node-ID sequence by a single left-to-right
scan. At position `i`, the smallest block length `k` in `1..4` for which the block
`seq[i:i+k]` is immediately repeated is chosen; all consecutive repetitions of that block are
replaced by one step `{"node_ids": block, "repeated": true}`. Otherwise `seq[i]` becomes a step
with `repeated: false`. The rule is deterministic, documented, and reversible in the sense that
each variant lists its exact `path_ids`.

Variant identity: SHA-256 of the compact JSON
`["journeygraph.variant/v1", [repeated, node_id, ...], ...]` using the same encoding rules as
other identities. Each variant reports `variant_id`, `steps` (with labels), `trace_count`,
`rate`, `path_count`, `path_ids` (sorted), and `trace_outcomes`. Variants are sorted by
`variant_id`; the HTML sorts by trace count.

### Sequence patterns

Patterns are contiguous windows of length 2 and 3 over the **retry-collapsed** node sequence
(adjacent identical categories merged), so `A A B` contributes `A B` rather than `A A`. A
pattern is published when at least `min_support` distinct traces contain it. Each pattern
reports `pattern_id` (`journeygraph.sequence/v1`), `node_ids`, `labels`, `length`,
`trace_count`, and `trace_outcomes`. At most 50 patterns are published, ranked by trace count
descending, then length descending, then ID; the publication order is by `pattern_id`.

### Sequence association finding

Same rule as `outcome_association`, applied to published patterns of length 2 and 3: at least
`min_support` known-outcome traces contain the sequence and at least `min_support` do not, and
the success rates differ by at least 0.20. Its priority is directly after
`outcome_association`. To avoid restating single-category findings, a sequence is skipped when
one of its categories already produced an `outcome_association` with the same visiting and
non-visiting support.

### Filters

- `--outcome success,failure,...` keeps traces whose reconciled outcome is listed. Values must
  be standard outcomes; anything else is a usage error (exit code 2).
- `--since` and `--until` take ISO 8601 timestamps with an explicit offset or `Z`. A trace is
  kept when its first event is at or after `since` and strictly before `until`.
- Filters apply after normalization and before analysis; `normalized.jsonl` contains only
  retained traces so artifacts stay consistent.
- `filters` in the payload records `outcomes`, `since`, `until` (normalized UTC strings or
  `null`), `input_trace_count`, and `retained_trace_count`.
- A filter that retains no traces is a validation error (exit code 2), because an empty
  analysis is not useful and would hide a typo.

## Test strategy

- Unit: variant collapsing (single repeats, block repeats, nested and overlapping cases,
  minimal-block preference, length-4 limit), identity stability, pattern windows over
  retry-collapsed sequences, support threshold and cap, sequence-association threshold and
  redundancy rule, filter parsing and boundaries.
- Functional (installed CLI): a fixture where every exact path is unique but three variants
  emerge; a sequence association that no single category explains; `--outcome`, `--since`,
  `--until` behavior, empty-result error, and invalid values.
- Schema sweep and contract tests updated for 1.2; byte-identical artifacts under trace
  reordering.

## Acceptance criteria

- [x] `analysis.json` reports `schema_version: "1.2"` and validates against the updated schema.
- [x] Variants, patterns, sequence associations, and filters follow the definitions above.
- [x] The HTML report shows variants and recurring sequences before exact paths.
- [x] `make verify` passes with coverage at or above 90%.
- [x] README, schema, CLI, architecture docs, and changelog are updated.

## Progress

- [x] 2026-11-08: Branched `feat/path-variants` from `feat/readable-report` at `d9cff94`.
- [x] Variants, patterns, sequence associations, filters, schema 1.2, HTML, docs, tests.

## Decision log

- **Emit variants alongside exact paths, not instead of them.** No configuration switch and no
  change to the meaning of `paths`.
- **Retry-collapsed windows for patterns.** Adjacent repetitions are already reported by
  `retries`; counting `A A` as a sequence would duplicate them.
- **Block length limit 4.** Keeps the rule cheap and explainable; longer cycles remain visible
  in `loops`.
- **Node keys deferred.** Changing node granularity changes node identity and needs a separate
  versioned plan.

## Outcomes and retrospective

Verification on macOS with Python 3.12 on 2026-11-08:

- `make verify` passed: 370 tests passed and 9 intentionally rejected fixtures skipped,
  95.19% combined branch-aware coverage, plus Ruff, mypy, wheel smoke, documentation, corpus,
  dependency audit, Bandit, and secret scanning.
- `make benchmark` (2,000 traces): analysis including graph 1.81 s versus 1.62 s after the
  readable-report plan; end-to-end 6.47 s. One local run, not a general performance claim.
- On the new functional fixture, 12 exact paths collapse into 4 variants, and three sequence
  associations explain outcome differences that no single category explains (for example,
  retrieval before the model versus after it).
- The packaged demo still has 9 distinct variants because its synthetic traces differ in
  categories rather than repetitions; it gains one sequence association and 5 recurring
  sequences.

Follow-ups: configurable node keys, deterministic sampling, and a mutation run for the new
modules.
