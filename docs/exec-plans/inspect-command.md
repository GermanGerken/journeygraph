# Inspect Command ExecPlan

This living plan implements the fifth item of Stage 4 of the product roadmap: shorten the path
from "my own export" to a first report. `journeygraph inspect` reads a sample of a JSON Lines,
CSV, or Parquet file, describes its fields without printing their values, and writes a draft
field mapping (see [field-mapping.md](field-mapping.md)) for the user to review.

Status: **implemented on `feat/inspect`; awaiting review.** Approved by the owner on
2026-11-08 with the proposed defaults.

## Purpose and observable outcome

```bash
journeygraph inspect export.jsonl --mapping-out mapping.toml
journeygraph validate export.jsonl --mapping mapping.toml --normalized-out events.jsonl
```

`inspect` prints one line per source leaf path: how many sampled records contain it, how many
are null, the observed JSON types, shape hints (identifier-like, RFC 3339 timestamp, epoch
seconds/milliseconds/microseconds/nanoseconds, small number of distinct values), and the
canonical field it suggests, if any. `--mapping-out` writes a commented TOML draft. Required
fields it cannot fill are left as commented `TODO` lines, so the draft fails `validate` until a
person completes it; nothing is silently guessed into a valid-looking mapping.

## Scope and non-goals

In scope: a pure inspection module, deterministic suggestion heuristics, the command, a draft
mapping writer that reuses the mapping parser for self-checking, documentation, and tests.

Out of scope: machine learning or LLM-based inference, network access, OTLP inputs (they have
a dedicated importer), automatic analysis after inspection, and vendor presets.

## Contract decisions

- Command: `journeygraph inspect INPUT [--format auto|jsonl|csv|parquet] [--sample N]
  [--mapping-out PATH] [--force] [--show-values]`. `--sample` defaults to 1,000 records (the
  first N in file order) and must be a positive integer.
- Output never contains source values by default: only paths, counts, types, and hints.
  Distinct-value counts are bucketed (`1`, `2-10`, `11-100`, `>100`) and computed from hashes
  held only in memory.
- `--show-values` is an explicit opt-in that adds, for paths suggested as `status`, `outcome`,
  or `operation_type` only, up to 20 distinct values that are short identifier-like tokens
  (`^[A-Za-z0-9_.:-]{1,64}$`), so the draft can contain a `[values.*]` table. Free text never
  qualifies.
- Suggestions are deterministic: a fixed table of name tokens per canonical field (for example
  `trace`, `session`, `conversation` for `trace_id`; `latency`, `duration`, `elapsed` for
  durations) combined with shape checks (an epoch-millisecond integer cannot be a
  `component`). Ties break on the shortest path, then lexical order. Each suggestion carries a
  one-word reason (`name`, `name+shape`).
- Epoch units are inferred from magnitude in a documented range table; a start/end pair with
  the same unit becomes a `[duration]` pair. Duration units are inferred from name suffixes
  (`_ms`, `_s`, `_seconds`, `_us`, `_ns`), defaulting to milliseconds.
- With `--show-values`, value suggestions map tokens containing `error`, `fail`, `ok`,
  `success`, or `unset` to canonical statuses or outcomes, and lowercased tokens that are
  recognized canonical operation types to themselves; anything else is left commented.
- The draft is parsed with the mapping parser before it is written; a draft with all required
  fields filled must parse. `--mapping-out` refuses to overwrite without `--force` and cannot
  equal the input path.
- Exit codes: `0` success; `2` unreadable format or invalid options; `3` I/O; `4` output
  conflict. Inspection is advisory and never fails because suggestions are incomplete.

## Privacy and security

- Paths (field names) are printed, as they are needed to write a mapping; the docs warn that
  field names can themselves be sensitive. Values are printed only with `--show-values` and
  only under the restrictions above.
- Nothing is written except the explicit `--mapping-out` file.

## Test strategy

- Unit: path and type collection, hints and buckets, epoch-unit inference at range edges,
  suggestion ranking and tie-breaks, value suggestions, draft rendering (TODO lines,
  quoting of dotted keys, round trip through `parse_mapping`).
- Functional (installed CLI): on the committed `mapped_export.jsonl` fixture,
  `inspect --show-values --mapping-out` produces a draft that, unchanged, validates the export
  and yields the same traces, steps, parents, timestamps, durations, outcomes, costs, and
  statuses as the canonical fixture (operation-type labels may differ from the hand-written
  mapping). On `mapped_export.csv`, whose statuses are the opaque codes `1` and `2`, the draft
  leaves them as `TODO` lines and validation fails until a person maps them. Default output and
  drafts contain no fixture value; invalid `--sample`, an existing `--mapping-out` without
  `--force`, the input as `--mapping-out`, and an OTLP format are rejected.

## Acceptance criteria

- [x] `inspect` reports paths, counts, types, hints, and suggestions without values by default.
- [x] The JSONL fixture's draft (with `--show-values`) validates unchanged and reproduces the
  canonical events' structure; the CSV draft fails only on its opaque status codes, by design.
- [x] `make verify` passes with coverage at or above 90%; mutation results are recorded.
- [x] README, CLI, schema (field mappings), privacy, and architecture docs and the changelog
  are updated.

## Milestones

1. Inspection module: sampling, leaf paths, types, hints, buckets.
2. Suggestion heuristics and draft mapping rendering.
3. CLI command and output safety.
4. Fixtures, tests, documentation, verification.

## Resolved questions

- `--show-values` ships as an explicit opt-in limited to identifier-like tokens of three fields.
- The default sample is 1,000 records; `--sample` changes it.

## Progress

- [x] 2026-11-08: Owner approved the plan; implemented on `feat/inspect` from `main` after the
  v0.2.0 release.
- [x] Milestones 1-4: `journeygraph.ingestion.inspection`, the `inspect` command, unit and
  functional tests on the existing mapping fixtures, and documentation.

## Decision log

- **Advisory, never authoritative.** A wrong guess that validates would silently mislabel a
  journey, so unfilled required fields stay as `TODO` lines and every suggestion names its
  reason.
- **No values by default.** Inspection runs on exports a user has not yet reviewed, which is
  exactly when unexpected sensitive content is most likely.
- **Acceptance adjusted for opaque codes.** The plan expected both fixture drafts to validate
  unchanged. The CSV encodes status as `1`/`2`, which no name or shape heuristic can map
  safely, so that draft deliberately stops at `TODO` lines; guessing would violate the
  advisory principle above.
- **The whole file is read, then sampled.** Readers return complete record tuples; `--sample`
  bounds profiling work and output, not memory. Streaming readers belong to the scale stage.
- **Values are counted through hashes.** Distinct counts use SHA-256 digests held in memory
  (at most 101 per path) so buckets need no stored values.

## Outcomes and retrospective

Verification on macOS with Python 3.12 on 2026-11-08: `make verify` passed with 578 tests
(11 intentionally skipped) and 96.71% combined branch-aware coverage, plus Ruff, mypy, wheel
smoke, documentation, corpus, dependency audit, Bandit, and secret scanning. On the JSON Lines
fixture every canonical field, the duration pair, the epoch unit, the `environment` metadata
key, and (with `--show-values`) the status and operation-type value maps are suggested
correctly; on the CSV fixture everything except the opaque status codes is.

`make mutation` from a clean `mutants/` directory: the first run killed 629 of 919 mutants in
`inspection.py` (68.4%), mostly surviving in heuristic scores and report layout. Exact score,
bucket-edge, report, and draft tests raised it to 770 of 929 (82.9%).

Follow-ups: streaming readers so `--sample` also bounds memory, and vendor presets that start
from an inspected draft.
