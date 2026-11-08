# LangSmith Preset ExecPlan

This short living plan completes the vendor item of Stage 4: a packaged, experimental
`langsmith-runs` preset next to the Langfuse and Phoenix presets
([vendor-presets.md](vendor-presets.md)), and the one mapping extension it needs.

Status: **implemented on `feat/stage4-complete`; awaiting review.** The owner asked on
2026-11-08 to complete Stage 4 before preparing 0.3.0, which this plan records as approval.

## Sources (checked 2026-11-08)

- [Run (span) data format](https://docs.langchain.com/langsmith/run-data-format)
- [Bulk data export](https://docs.langchain.com/langsmith/data-export)
- [Query runs API](https://docs.langchain.com/langsmith/smith-api/runs/query-runs) and
  [migration from `list_runs`](https://docs.langchain.com/langsmith/smithdb-sdk-migration-query-runs)
- [Export traces](https://docs.langchain.com/langsmith/export-traces): legacy `list_runs` /
  `read_run` are deprecated and removed on LangSmith Cloud on 2027-01-31.

### What the sources establish

The documented, non-deprecated record shape is the run object returned in `items` by
`client.runs.query(...)` / `POST /api/v2/runs/query`: `id`, `trace_id`, `parent_run_ids`
(ancestors from the root to the direct parent, so the parent is the last element),
`name`, `run_type` (`TOOL`, `CHAIN`, `LLM`, `RETRIEVER`, `EMBEDDING`, `PROMPT`, `PARSER`),
`status` (`SUCCESS`, `ERROR`, `PENDING`), RFC 3339 `start_time` and `end_time` (`null` while a
run is unfinished), `latency_seconds`, `prompt_tokens`, `completion_tokens`, `total_cost`
("estimated USD"), `inputs`, `outputs`, `metadata`, `extra`, `tags`, and `thread_id`. In this
API token and cost fields report only a run's own usage. Fields are returned only when
requested through `selects`. Bulk export writes Parquet whose physical types are not
documented, and the legacy schema uses lowercase enums, `parent_run_id`, and naive
timestamps in its example.

## Contract decisions

- Mapping paths gain an array index suffix: `name[0]`, `name[-1]`. It applies to the segment
  before it (a quoted segment keeps brackets literal: `"a[0]"` is a key, `"a"[0]` an index).
  An index outside the array, or a non-array value, is a missing value.
- Preset `langsmith-runs`, for run objects written one per line:

| Canonical | Source | Notes |
| --- | --- | --- |
| `trace_id`, `step_id` | `trace_id`, `id` | |
| `parent_step_id` | `parent_run_ids[-1]` | absent for a root (empty array) |
| `timestamp` | `start_time` | `iso8601` |
| `duration_ms` | `end_time - start_time` | an unfinished run is a validation error naming the paths |
| `operation_type` | `run_type` | lowercased canonical types; `PARSER` kept as `parser` with the unknown-type warning |
| `component` | `name` | |
| `status` | `status` | `SUCCESS` → `ok`, `ERROR` → `error`, `PENDING` → `unset`; lowercase spellings mapped the same |
| `input_tokens`, `output_tokens` | `prompt_tokens`, `completion_tokens` | |
| `cost_usd` | `total_cost` | |
| `outcome` | not mapped | |

  `inputs`, `outputs`, `metadata`, `extra`, `tags`, `thread_id`, and error text are not read.
- Requires selecting at least `ID`, `TRACE_ID`, `PARENT_RUN_IDS`, `NAME`, `RUN_TYPE`, `STATUS`,
  `START_TIME`, and `END_TIME`; the docs list the select names.

## Non-goals

Bulk-export Parquet (types undocumented), the legacy `list_runs` shape, feedback as outcomes,
and any claim of tested compatibility with real LangSmith output.

## Tests

Unit: index parsing, lookup, and ignored-path accounting. Integration and functional: a
synthetic run-object fixture with a root, nested children, an `ERROR` run, `PENDING`, a
`PARSER` run, and an unfinished run (negative); sensitive fields never reach artifacts.

## Progress

- [x] 2026-11-08: Read the sources above; implemented the index suffix, preset, fixture,
  tests, and documentation.

## Decision log

- **Target the v2 query shape.** It is the only fully documented, non-deprecated record shape,
  and its per-run token and cost fields do not double-count child usage.
- **Generic array index, not a LangSmith special case.** Taking the last ancestor is a path
  feature any mapping can use.

## Outcomes and retrospective

Verification on macOS with Python 3.12 on 2026-11-08 (together with the OTLP protobuf plan):
`make verify` passed with 648 tests (14 intentionally skipped) and 96.81% combined coverage.
The preset analyzes its synthetic fixture (3 traces, 10 runs); no input, output, metadata,
thread, or error text reaches any artifact. `make mutation`: `mapping.py` 672 of 750 killed
(89.6%) including the array index, `presets.py` 18 of 23.
