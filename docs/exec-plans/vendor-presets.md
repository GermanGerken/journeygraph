# Vendor Mapping Presets ExecPlan

This living plan implements the third item of Stage 4 of the product roadmap: analyze exports
from two popular open-source LLM observability tools, Langfuse and Arize Phoenix, without
writing a mapping. It ships packaged, reviewed [field mappings](field-mapping.md) selected by
name, plus one small mapping extension that Langfuse timestamps require. It adds no vendor
code path: presets are ordinary mapping documents applied by the existing mapper.

Status: **implemented on `feat/vendor-presets`; awaiting review.** Approved by the owner on
2026-11-08 with the proposed defaults.

## Purpose and observable outcome

```bash
journeygraph analyze observations.jsonl --preset langfuse-observations --output-dir report
journeygraph analyze spans.jsonl --preset phoenix-spans --output-dir report
journeygraph presets            # lists presets, their sources, and maturity
journeygraph presets --show langfuse-observations   # prints the TOML to copy and adapt
```

## Sources (checked 2026-11-08)

Field names below come only from vendor documentation; no real export is committed or was
used. Both presets are therefore **experimental** and make no compatibility claim beyond the
documented shapes.

- Langfuse: [Export to blob storage](https://langfuse.com/docs/api-and-data-platform/features/export-to-blob-storage)
  (field reference for the current enriched `observations_v2/` export) and
  [Export from UI](https://langfuse.com/docs/api-and-data-platform/features/export-from-ui).
- Arize Phoenix: [Export data and query spans](https://arize.com/docs/phoenix/tracing/how-to-tracing/importing-and-exporting-traces/extract-data-from-spans)
  and the [REST span list API](https://arize.com/docs/phoenix/sdk-api-reference/rest-api/api-reference/spans/list-spans-with-simple-filters-no-dsl).

### What the sources establish

Langfuse `observations_v2/` (Parquet default, CSV, JSON, or JSONL; one row per observation):
`id`, `trace_id`, `parent_observation_id` (empty for a root), `type` (`SPAN`, `GENERATION`,
`EVENT`, `AGENT`, `TOOL`, `CHAIN`, `RETRIEVER`, `EVALUATOR`, `EMBEDDING`, `GUARDRAIL`), `name`,
`start_time`, `end_time` (nullable), `level` (`DEBUG`, `DEFAULT`, `WARNING`, `ERROR`),
`provided_model_name`, `usage_details` (object with keys such as `input`, `output`, `total`),
`total_cost` (USD, `0` when no cost was recorded), `latency` (seconds for integrations created
on or after 2026-04-01, milliseconds before), `environment`, `session_id`, `user_id`, `input`,
`output`, and `metadata`. Timestamps in JSON and JSONL are `YYYY-MM-DD HH:MM:SS.ffffff` in UTC
with no offset. The documentation does not describe how objects are flattened in CSV or
Parquet, and the UI offers only CSV and JSON with unlisted columns. The legacy
`observations/` file is deprecated and stops on Langfuse Cloud on 2026-11-16.

Phoenix: the documented span object (REST API) has `context.trace_id`, `context.span_id`,
`parent_id` (nullable), `name`, `span_kind` (`LLM`, `CHAIN`, `TOOL`, `RETRIEVER`, `EMBEDDING`,
`AGENT`, `RERANKER`, `GUARDRAIL`, `EVALUATOR`, `DECISION`, `UNKNOWN`), timezone-aware
`start_time` and `end_time`, `status_code` (`OK`, `ERROR`, `UNSET`), `status_message`, and an
`attributes` object with dotted keys such as `llm.model_name`, `llm.token_count.prompt`, and
`llm.token_count.completion`. Phoenix documents no span file format and no default column list
for `get_spans_dataframe()`; span-level cost attributes are not documented.

## Scope and non-goals

In scope:

- packaged presets `langfuse-observations` (enriched `observations_v2` JSON Lines or JSON
  records) and `phoenix-spans` (REST span objects written one per line);
- `--preset NAME` on `validate`, `analyze`, `diff`, and `check`, mutually exclusive with
  `--mapping`;
- `journeygraph presets [--show NAME]`;
- the mapping extension `[timestamp] unit = "utc_naive"` (below);
- synthetic fixtures shaped after the documented fields, documentation, and tests.

Out of scope: the deprecated Langfuse legacy files, Langfuse CSV and Parquet layouts (object
flattening is undocumented; users can adapt the preset after `inspect`), Phoenix DataFrame
column layouts (undocumented), API clients or network access, scores or evaluations as
outcomes, LangSmith, and any claim of tested compatibility with real vendor output.

## Contract decisions

### Mapping extension: `utc_naive` timestamps

`[timestamp] unit = "utc_naive"` accepts `YYYY-MM-DD HH:MM:SS[.fraction]` or the same with `T`,
with up to nine fractional digits and **no** offset, and interprets it as UTC. It converts
exactly to RFC 3339 with `Z`. A value carrying an offset or `Z` is rejected under this unit, so
a mixed file cannot be silently misread. Duration pairs use the same unit.

### `langfuse-observations`

| Canonical | Source | Notes |
| --- | --- | --- |
| `trace_id` | `trace_id` | |
| `step_id` | `id` | |
| `parent_step_id` | `parent_observation_id` | empty string means root, as in canonical input |
| `timestamp` | `start_time` | `utc_naive` |
| `duration_ms` | `end_time - start_time` | `latency` is not used because its unit depends on the integration date; a null `end_time` is a validation error naming the path |
| `operation_type` | `type` | value map: `GENERATION` → `llm`, `EVENT` → `internal`, other documented types lowercased to the canonical type of the same name |
| `component` | `name` | |
| `status` | `level` | `ERROR` → `error`; `DEBUG`, `DEFAULT`, `WARNING` → `ok` |
| `input_tokens`, `output_tokens` | `usage_details.input`, `usage_details.output` | |
| `cost_usd` | `total_cost` | the documented `0` for "no cost recorded" is indistinguishable from a real zero; the docs say so |
| metadata `environment`, `model` | `environment`, `provided_model_name` | |
| `outcome` | not mapped | traces are `unknown` unless the user adds a mapping |

`session_id`, `user_id`, `input`, `output`, and `metadata` are never read, so they are counted
as ignored fields; several are also on the permanent denylist.

### `phoenix-spans`

| Canonical | Source | Notes |
| --- | --- | --- |
| `trace_id`, `step_id` | `context.trace_id`, `context.span_id` | |
| `parent_step_id` | `parent_id` | |
| `timestamp` | `start_time` | `iso8601` |
| `duration_ms` | `end_time - start_time` | |
| `operation_type` | `span_kind` | lowercased canonical types; `UNKNOWN` → `unspecified`; `DECISION` passes through as `decision` with the existing unknown-type warning, since no canonical type means the same |
| `component` | `name` | |
| `status` | `status_code` | `OK`, `ERROR`, `UNSET` → `ok`, `error`, `unset` |
| `input_tokens`, `output_tokens` | `attributes."llm.token_count.prompt"`, `attributes."llm.token_count.completion"` | |
| metadata `model` | `attributes."llm.model_name"` | |
| `cost_usd`, `outcome` | not mapped | not documented per span |

### CLI and packaging

- Presets are TOML files packaged under `journeygraph/data/presets/` and parsed with the same
  `parse_mapping`; a test parses every packaged preset.
- `--preset` with `--mapping`, an unknown preset name, or an OTLP format is a usage error
  (exit `2`); the error lists available presets.
- `journeygraph presets` prints name, intended input, maturity, and source URLs;
  `--show NAME` prints the TOML so users can adapt it into their own `--mapping` file.

## Test strategy

- Unit: `utc_naive` parsing (space and `T`, 0-9 fractional digits, rejection of offsets and
  malformed values, pairs); preset loading and listing; every packaged preset parses.
- Integration: each preset applied to its synthetic fixture produces the expected canonical
  events (hand-checked), including a root with an empty parent, an `ERROR` level, a missing
  `end_time`, and unknown span kinds.
- Functional (installed CLI): `analyze --preset` on both fixtures; `presets` and
  `presets --show`; invalid combinations exit 2 with no artifacts; denylisted fields such as
  `user_id` and `input` never appear in artifacts.

## Acceptance criteria

- [x] `--preset langfuse-observations` and `--preset phoenix-spans` analyze their synthetic
  fixtures end to end.
- [x] `utc_naive` is documented and exact to the nanosecond.
- [x] Presets and docs cite the vendor pages and date they were checked, and are labelled
  experimental with no compatibility claim.
- [x] `make verify` passes with coverage at or above 90%; mutation results are recorded.
- [x] README, CLI, schema, privacy docs, and the changelog are updated.

## Milestones

1. `utc_naive` in the mapping module.
2. Packaged presets, loader, `--preset`, and `presets` command.
3. Synthetic fixtures and tests.
4. Documentation and verification.

## Resolved questions

- Presets ship now as experimental, documented-shape only; the real-trace discovery process
  can upgrade their maturity later.
- Langfuse `WARNING` maps to `ok`; canonical `status` has no warning level.

## Progress

- [x] 2026-11-08: Read the Langfuse and Phoenix documentation listed above; the owner approved
  the plan; branched `feat/vendor-presets` from `main`.
- [x] Milestones 1-4: `utc_naive`, packaged presets with `--preset` and `presets`, synthetic
  fixtures (`langfuse_observations.jsonl`, `phoenix_spans.jsonl`), unit, integration, and
  functional tests, distribution checks for the packaged TOML files, and documentation.

## Decision log

- **Presets are data, not importers.** The mapping engine already validates and filters; a
  preset adds no vendor code path, keeps provider knowledge reviewable in one TOML file, and
  can be copied and adapted.
- **Use end minus start, not Langfuse `latency`.** The documented unit of `latency` changed by
  integration creation date, which a preset cannot detect.
- **Documented shapes only.** Both vendors leave file layouts partly undocumented, so the
  presets cover exactly the documented record shapes and say so.
- **Wheel and sdist must contain the presets.** `verify_distribution.py` now requires both
  TOML files and `verify_wheel.py` runs `journeygraph presets` from the installed wheel, so a
  packaging regression cannot ship silently.
- **Empty model names are kept.** Langfuse writes `""` for a missing `provided_model_name`, and
  the mapping copies it into `model` metadata as an empty string, exactly as canonical input
  would; filtering empty metadata would be a general semantic change outside this plan.

## Outcomes and retrospective

Verification on macOS with Python 3.12 on 2026-11-08: `make verify` passed with 604 tests
(13 intentionally skipped) and 96.76% combined branch-aware coverage, plus Ruff, mypy, wheel
smoke (now including `journeygraph presets` from the installed wheel), documentation, corpus,
dependency audit, Bandit, and secret scanning. Both presets analyze their synthetic fixtures
end to end; no fixture value from sessions, users, inputs, outputs, or status messages reaches
any artifact.

`make mutation` from a clean `mutants/` directory: killed mutants `mapping.py` 646 of 718
(90.0%, including `utc_naive`) and `presets.py` 18 of 23 (78.3%; survivors change listing
text checked only through the CLI).

Follow-ups: upgrade preset maturity once a sanitized real export from each tool passes the
real-trace discovery process; consider Langfuse CSV/Parquet and Phoenix DataFrame layouts if
their flattening becomes documented.
