# Field Mapping ExecPlan

This living plan implements the second item of Stage 4 of the product roadmap: let users analyze
their own JSON Lines, CSV, or Parquet exports without writing a conversion script. A small,
declarative TOML file maps source fields to the canonical `journeygraph.event/v1` fields before
the existing validation runs. It does not change the canonical schema, identities, analysis
payload, or the privacy boundary.

Status: **implemented on `feat/field-mapping`; awaiting review.** Approved by the owner on
2026-11-08 with the proposed defaults.

## Purpose and observable outcome

Today a user whose export says `session.id`, `span.name`, and `start_time_unix_ms` must first
write Python to produce canonical events. After this plan:

```bash
journeygraph analyze my-export.jsonl --mapping mapping.toml --output-dir report
```

reads each source object, builds a canonical event from the mapping, and then validates,
normalizes, and analyzes it exactly as if the canonical file had been supplied. `validate`,
`diff`, and `check` accept the same option, and `validate --mapping ... --normalized-out`
writes the mapped canonical events so users can inspect the result.

## Scope and non-goals

In scope: a pure mapping module, TOML parsing and validation, the `--mapping` option on
`validate`, `analyze`, `diff`, and `check`, documentation, synthetic fixtures, and tests.

Out of scope: arbitrary expressions, regular expressions, scripting, network lookups, joins
between records, nested-array flattening (one source object is one event), OTLP inputs (which
already have a dedicated importer), automatic mapping inference (`journeygraph inspect`, a
separate plan), and vendor presets (the Langfuse and Phoenix importers are separate plans).

## Mapping document

```toml
mapping_version = "1"

[fields]                      # canonical field = dotted source path
trace_id = "session.id"
step_id = "span.id"
parent_step_id = "span.parent_id"
timestamp = "start_time"
operation_type = "span.kind"
component = "attributes.tool.name"
status = "status.code"
outcome = "result"
input_tokens = "usage.prompt_tokens"
output_tokens = "usage.completion_tokens"
cost_usd = "usage.cost"

[duration]                    # either a single field or an end - start pair
end = "end_time"              # same unit as timestamp
start = "start_time"
# field = "latency"; unit = "s"   (alternative)

[timestamp]
unit = "unix_ms"              # iso8601 (default), unix_s, unix_ms, unix_us, unix_ns

[constants]                   # literal canonical values used when no field is mapped
operation_type = "tool"

[values.status]               # exact source value -> canonical value
STATUS_CODE_OK = "ok"
STATUS_CODE_ERROR = "error"
STATUS_CODE_UNSET = "unset"

[values.operation_type]
LLM = "llm"
TOOL = "tool"

[metadata]                    # metadata key = dotted source path
environment = "resource.deployment.environment"
```

Rules:

- `schema_version` is implied (`1.0`) and cannot be mapped.
- A dotted path walks nested objects; a key that itself contains a dot is addressed with a
  quoted segment (`attributes."tool.name"`). For CSV and Parquet, a path is a column name.
- A canonical field may come from `[fields]` or `[constants]`, never both. Required fields
  that are neither mapped nor constant are a mapping error before any record is read.
- `[values.<field>]` applies only to `status`, `outcome`, and `operation_type`, matches exact
  strings, and leaves unmatched values unchanged for normal validation to accept or reject.
- Timestamp units convert exact integers or decimals to RFC 3339 UTC without floating-point
  rounding. Duration from a pair uses the timestamp unit; a single duration field accepts
  `ms` (default), `s`, `us`, or `ns`.
- Missing paths yield a missing canonical field, so the existing validation reports it with the
  record location and, additionally, the source path.
- Unknown tables or keys, wrong types, and unsupported units are usage errors (exit 2).

## Privacy and security

- Only mapped source paths are read into canonical fields. Unmapped source fields are never
  copied; the dataset gains one `unmapped_source_fields_ignored` warning with a count, not the
  field names or values.
- Metadata mapped through `[metadata]` still passes the existing allowlist and the permanent
  sensitive-key denylist: a mapping cannot retain `api_key`, prompts, or any key that is not
  default-allowed or passed with `--allow-metadata-key`.
- The mapping file is parsed with standard-library `tomllib`; no code is evaluated.

## Contract decisions

- `--mapping` is accepted with `--format jsonl`, `csv`, `parquet`, or `auto` (by extension) and
  rejected with OTLP formats.
- With `--mapping`, CSV no longer requires canonical column names; the canonical header check
  moves after mapping.
- Reports and `analysis.json` are byte-identical to analyzing the equivalent canonical file,
  except for the added mapping warning. The payload records no mapping content, so a mapping
  file cannot leak source paths into shared artifacts.
- `validate --mapping FILE --normalized-out PATH` writes the mapped canonical JSON Lines; no
  separate command was added (see the decision log).
- With a mapping, every Parquet timestamp column is presented as exact RFC 3339 text, because
  PyArrow cannot convert nanosecond timestamps to Python `datetime` values.

## Test strategy

- Unit: path parsing (quoted segments, missing segments, non-object intermediate values),
  timestamp and duration unit conversion with exact decimals, value maps, constants, and every
  mapping-document error.
- Integration: a synthetic nested JSONL fixture and an equivalent CSV fixture both map to the
  same normalized events as a committed canonical fixture.
- Functional (installed CLI): `analyze --mapping` equals `analyze` on the canonical fixture
  (apart from the warning); `validate --normalized-out` writes the canonical file; invalid
  mappings exit 2 with no artifacts; a mapped `api_key` metadata key is still excluded.

## Acceptance criteria

- [x] `--mapping` works on `validate`, `analyze`, `diff`, and `check`; `validate
  --normalized-out` writes mapped canonical JSONL.
- [x] Mapped analysis equals canonical analysis apart from the documented warning.
- [x] Metadata allowlist and denylist apply unchanged.
- [x] `make verify` passes with coverage at or above 90%; mutation results are recorded.
- [x] README, schema, CLI, privacy, and architecture docs and the changelog are updated.

## Milestones

1. Mapping document parsing and validation (`journeygraph.ingestion.mapping`).
2. Record mapping with path lookup, units, value maps, and constants.
3. Reader, API, and CLI wiring, including the CSV and Parquet header change.
4. Fixtures, functional tests, documentation, verification.

## Resolved questions

- A way to inspect mapped events ships in this plan, as `validate --normalized-out` (below).
- Outcome semantics are unchanged: a mapping sets `outcome` per event, and the existing
  per-trace reconciliation applies.

## Progress

- [x] 2026-11-08: Owner approved the plan; branched `feat/field-mapping` from `main`.
- [x] Milestones 1-4: mapping module, reader/API/CLI wiring, synthetic fixtures
  (`mapped_export.jsonl`, `mapped_export.csv`, their mappings, and `mapped_canonical.jsonl`),
  unit, integration, and functional tests, and documentation.

## Decision log

- **Declarative TOML, no expressions.** Keeps mapping reviewable, deterministic, and safe to run
  on untrusted exports.
- **Map before validation.** Reuses every canonical rule and error message instead of
  duplicating validation for each source shape.
- **No separate `map` command.** `validate --mapping FILE --normalized-out PATH` already writes
  exactly the mapped canonical events with the existing output-safety rules; a second command
  would duplicate it.
- **Report missing required paths in the mapper.** Canonical validation cannot know the source
  path, so the mapper emits `mapped_field_missing` with the path, and never the value.
- **Count ignored fields, never name them.** Field names can be sensitive; the warning carries
  only the number of distinct unread leaf paths.
- **Parquet timestamps as text under a mapping.** PyArrow raises for nanosecond timestamps
  converted to `datetime`, and only the canonical `timestamp` column had a special path.
  Converting every timestamp column to exact RFC 3339 text keeps nanoseconds and keeps naive
  timestamps rejected by canonical validation.

## Outcomes and retrospective

Verification on macOS with Python 3.12 on 2026-11-08: `make verify` passed with 507 tests
(11 intentionally skipped) and 96.40% combined branch-aware coverage, plus Ruff, mypy, wheel
smoke, documentation, corpus, dependency audit, Bandit, and secret scanning. The nested JSON
Lines export (epoch milliseconds and an end-minus-start duration) and the flat CSV export
(ISO timestamps and seconds) both produce byte-identical `normalized.jsonl` to the canonical
fixture, and `analysis.json` differs only by the documented ignored-fields warning.

`make mutation` from a clean `mutants/` directory (unit and integration tests): killed mutants
`mapping.py` 593 of 667 (88.9%). A first run reused a stale `mutants/` cache and generated no
mutants for the new module; clearing the generated directory fixed it.

Follow-ups: `journeygraph inspect` to propose a mapping from a sample file, and vendor
importers (Langfuse, Arize Phoenix) that may ship as mapping presets where their exports are
flat enough.
