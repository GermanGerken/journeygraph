# Data and Analysis Schemas

JourneyGraph accepts existing local exports and normalizes them into one vendor-neutral event
model. The canonical event schema is `journeygraph.event/v1`; the current serialized
`schema_version` is the literal string `1.0`.

The packaged [`event-v1.schema.json`](../src/journeygraph/schemas/event-v1.schema.json)
describes the strict, privacy-filtered objects JourneyGraph emits in `normalized.jsonl`. It is
not a declaration that raw source objects must contain no other keys. Canonical JSONL, CSV,
and Parquet readers tolerate unknown top-level input fields so normalization can exclude each
one with an `unknown_field_excluded` warning. Excluded keys never appear in normalized output;
recognized fields still have to satisfy the canonical validation rules below.

## Canonical event fields

| Field | Required | Contract |
| --- | --- | --- |
| `schema_version` | yes | String or scalar representation equal to `1.0`; normalized output is the string `1.0`. |
| `trace_id` | yes | 1–128 ASCII letters, digits, `.`, `_`, `:`, or `-`; first character must be alphanumeric. |
| `step_id` | yes | Same identifier rule; unique within a trace after duplicate handling. |
| `parent_step_id` | no | Same identifier rule; null or empty means no known parent. |
| `timestamp` | yes | RFC 3339 date-time with `Z` or an explicit `±HH:MM` offset and up to nine fractional digits. |
| `operation_type` | yes | 1–64 ASCII letters, digits, `.`, `_`, or `-`; first character must be a letter. It is normalized to lowercase. |
| `component` | yes | Non-empty operational label after trimming, at most 256 Unicode scalar characters; XML-invalid controls and unpaired surrogates are rejected. |
| `duration_ms` | yes | Finite non-negative number no greater than `1000000000000000`. |
| `status` | yes | `unset`, `ok`, or `error`, normalized to lowercase. |
| `outcome` | no | `success`, `failure`, `handoff`, `dropoff`, or `unknown`, normalized to lowercase. |
| `input_tokens` | no | Non-negative whole number no greater than `1000000000000000`. |
| `output_tokens` | no | Non-negative whole number no greater than `1000000000000000`. |
| `cost_usd` | no | Finite non-negative decimal number no greater than `1000000000000000`. |
| `metadata` | no | Object whose retained values are string, number, boolean, or null; filtering rules are described in [Privacy](privacy.md). |

Boolean values are not accepted as numeric fields. NaN, positive or negative infinity,
negative values, fractional token counts, and values above the documented maximum are errors.
Non-integral duration and cost values may contain at most 15 significant decimal digits and
must round-trip through an ordinary finite JSON number without changing their decimal value.
This prevents silent precision loss and non-standard `Infinity` output.

Normalized timestamps use UTC with a trailing `Z`. Output normally uses six fractional
digits; it uses nine digits when an accepted timestamp contains exact sub-microsecond
precision that would otherwise be lost. The accepted RFC 3339 subset requires uppercase `T`
and `Z` and does not accept leap-second notation.

An unknown but syntactically valid `operation_type` is preserved with a warning. Currently
recognized types are:

```text
agent, chain, client, consumer, embedding, evaluator, guardrail, handoff,
internal, llm, model, outcome, producer, prompt, request, reranker, retrieval,
retriever, router, server, span, tool, unspecified, validation
```

These names are descriptive categories, not a promise of compatibility with a particular
framework.

### Minimal JSON Lines example

```json
{"schema_version":"1.0","trace_id":"trace-1","step_id":"step-1","timestamp":"2026-07-21T08:00:00Z","operation_type":"request","component":"user_request","duration_ms":4,"status":"ok"}
{"schema_version":"1.0","trace_id":"trace-1","step_id":"step-2","parent_step_id":"step-1","timestamp":"2026-07-21T08:00:00.125Z","operation_type":"outcome","component":"completed","duration_ms":1,"status":"ok","outcome":"success"}
```

JSON Lines input must be UTF-8 and contain one complete JSON object per non-blank line. A JSON
array is not accepted as canonical JSONL. Decoder-limit and invalid-UTF-8 failures are reported
as format errors rather than internal failures.

## CSV representation

CSV uses the same scalar field names as the canonical schema. The eight required fields must
be present in the header. Empty cells become null. Metadata uses columns named
`metadata.<key>`, for example:

```csv
schema_version,trace_id,step_id,parent_step_id,timestamp,operation_type,component,duration_ms,status,outcome,metadata.environment
1.0,trace-1,step-1,,2026-07-21T08:00:00Z,request,user_request,4,ok,,test
1.0,trace-1,step-2,step-1,2026-07-21T08:00:00.125Z,outcome,completed,1,ok,success,test
```

CSV is a canonical scalar transport. It does not accept nested metadata documents, empty or
duplicate column names, or rows wider than their header.

## Parquet representation

Parquet uses the same logical columns and requires the same eight required fields. Metadata
may be an Arrow struct that PyArrow decodes to a Python mapping; Arrow `Map` values are not
accepted as canonical metadata. Native Parquet timestamp values must carry a timezone.
Arrow timestamp units `s`, `ms`, `us`, and `ns` are converted to exact epoch nanoseconds;
sub-microsecond and pre-epoch values are preserved in canonical timestamp output.
Parquet decoding is optional and requires:

```bash
python -m pip install 'journeygraph[parquet]'
```

The default installation does not include PyArrow. Parquet support is an input adapter only;
the normalized output remains JSON Lines.

## Field mappings

Field mappings are experimental. `--mapping FILE` reads JSON Lines, CSV, or Parquet records of
any shape and builds one canonical event per source record from a TOML document before the
canonical validation in this page runs. Every canonical rule, error code, ordering, and
privacy filter then applies unchanged.

```toml
mapping_version = "1"

[fields]                      # canonical field = source path
trace_id = "session.id"
step_id = "span.id"
parent_step_id = "span.parent_id"
timestamp = "start_time_unix_ms"
operation_type = "span.kind"
component = 'attributes."tool.name"'
status = "status.code"
outcome = "result"
input_tokens = "usage.prompt_tokens"
output_tokens = "usage.completion_tokens"
cost_usd = "usage.cost"

[timestamp]
unit = "unix_ms"              # iso8601 (default), unix_s, unix_ms, unix_us, unix_ns

[duration]                    # a pair in the timestamp unit ...
start = "start_time_unix_ms"
end = "end_time_unix_ms"
# ... or one field: field = "latency", unit = "s"   (ms default, s, us, ns)

[constants]                   # literal values for canonical fields with no source path
# operation_type = "tool"

[values.status]               # exact source value -> canonical value
STATUS_CODE_OK = "ok"
STATUS_CODE_ERROR = "error"

[metadata]                    # metadata key = source path
environment = "resource.deployment.environment"
```

| Rule | Contract |
| --- | --- |
| Version | `mapping_version = "1"` is required. `schema_version` is implied and cannot be mapped. |
| Paths | Dots separate nested object keys; a double-quoted segment may contain dots (`attributes."tool.name"`). A top-level key equal to the whole path (for example a CSV column `metadata.env`) is matched first. Arrays are not traversed. |
| Coverage | `trace_id`, `step_id`, `timestamp`, `operation_type`, `component`, `duration_ms`, and `status` must each come from `[fields]`, `[constants]`, or (for the duration) `[duration]`. A field cannot be both mapped and constant; `timestamp` cannot be a constant. |
| Optional fields | `parent_step_id`, `outcome`, `input_tokens`, `output_tokens`, and `cost_usd`; a missing optional path leaves the field absent. |
| Missing values | A required field whose path is absent in a record is a `mapped_field_missing` error naming the record location and source path. |
| Timestamps | `iso8601` passes the value through unchanged (RFC 3339 strings or timezone-aware Parquet timestamps). Epoch units accept integers, decimal strings, and floats (by their shortest representation), convert exactly to nanoseconds, and must not need sub-nanosecond precision. |
| Durations | `[duration] field` with `unit` other than `ms` must be numeric. `start`/`end` subtract two instants in the timestamp unit; a negative result is rejected by canonical validation. `[duration]` and `fields.duration_ms` are mutually exclusive. |
| Value maps | `[values.status]`, `[values.outcome]`, and `[values.operation_type]` replace exact string or integer source values; other values pass through to canonical validation. |
| Metadata | `[metadata]` keys are subject to the same allowlist, `--allow-metadata-key`, and permanent denylist as canonical metadata. |
| Errors | Unknown tables or keys, wrong types, unsupported units, and incomplete coverage are usage errors (exit code `2`). Unconvertible values are `mapped_value_invalid` validation errors. Messages never echo source values. |

Only mapped paths are copied. The dataset gains one `unmapped_source_fields_ignored` warning
with the number of distinct source leaf paths that were not read; names and values of those
fields are not reported. Apart from that warning, analyzing a mapped export produces the
same `analysis.json` as analyzing the equivalent canonical file, and the payload contains no
mapping content. With a mapping, CSV and Parquet do not require canonical column names, and CSV
`metadata.*` columns are not split into metadata. With a mapping, every Parquet timestamp
column is presented as exact RFC 3339 text: timezone-aware columns in UTC with `Z` and full
nanosecond precision, naive columns without an offset (which canonical validation rejects).

## Experimental OTLP/JSON import

OTLP/JSON import is experimental and must be selected explicitly:

```bash
journeygraph validate export.json --format otlp-json
journeygraph validate collector-export.jsonl --format otlp-jsonl
```

`otlp-jsonl` reads OpenTelemetry Collector file-exporter output: each non-empty line is one
JSON-encoded `ExportTraceServiceRequest`, decoded exactly like an `otlp-json` body, and spans
of one trace may be spread across lines. Locations in errors are prefixed with the line
number. Compressed files and the Collector's protobuf file format are not supported. The
equivalence is tested by re-encoding the committed instrumented requests one span per line;
raw Collector captures themselves are not committed.

The importer accepts one uncompressed JSON-encoded OTLP/HTTP
`ExportTraceServiceRequest` body with this hierarchy:

```text
resourceSpans[].scopeSpans[].spans[]
```

It follows the official lowerCamelCase JSON field names, hexadecimal trace/span identifiers,
integer enum encoding, protobuf `AnyValue` wrappers, and Unix-nanosecond timestamps. It is
not a receiver, collector, live exporter, gRPC decoder, protobuf-binary decoder, gzip decoder,
or generic JSON trace importer.

The OpenTelemetry Collector file exporter with `format: json` writes a sequence of those
requests as JSONL, one request object per line. That file is neither the one-request OTLP/JSON
input above nor canonical JourneyGraph event JSONL, and is rejected by both readers. The
repository's [instrumented test-data harness](../test-data/README.md) performs an explicit,
offline Collector-JSONL-to-one-request preparation step for test fixtures; this does not widen
the product input boundary.

Each imported span must have a non-empty name, start and end timestamps, and valid trace and
span identifiers. Resource and span attribute keys must be unique within their respective
entity. An envelope containing no spans is rejected later as empty input. The importer ignores
scope details, schema URLs, trace state, flags, status messages, events, links, dropped-count
fields, and unknown fields rather than preserving them in the canonical model.

### OTLP field mapping

| OTLP source | Canonical field |
| --- | --- |
| `span.traceId` | `trace_id`, lowercased; exactly 32 non-zero hexadecimal characters. |
| `span.spanId` | `step_id`, lowercased; exactly 16 non-zero hexadecimal characters. |
| `span.parentSpanId` | `parent_step_id` when present; same span-ID rule. |
| `span.startTimeUnixNano` | `timestamp`, rendered in UTC; nine fractional digits are retained when required for exact sub-microsecond precision. |
| `endTimeUnixNano - startTimeUnixNano` | `duration_ms`; negative duration is an error. |
| `span.kind` | Base `operation_type`: `unspecified`, `internal`, `server`, `client`, `producer`, or `consumer`. |
| `span.status.code` | `status`: integer `0` → `unset`, `1` → `ok`, `2` → `error`. |
| `span.name` | Fallback `component`. |

The following selected attributes refine the mapping:

| Attribute | Use |
| --- | --- |
| `openinference.span.kind` | Overrides `operation_type` only for `LLM`, `EMBEDDING`, `CHAIN`, `RETRIEVER`, `RERANKER`, `TOOL`, `AGENT`, `GUARDRAIL`, `EVALUATOR`, or `PROMPT`. |
| `tool.name`, `agent.name`, `llm.model_name` | First available value becomes `component`; otherwise the span name is used. |
| `journeygraph.outcome` | Explicit canonical outcome after lowercase normalization and validation. |
| `llm.token_count.prompt`, `llm.token_count.completion` | Input and output tokens when non-negative integers. |
| `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | Token fallback when the corresponding `llm.token_count.*` value is absent. |
| `llm.cost.total` | Total cost when finite and non-negative. |
| `llm.cost.prompt`, `llm.cost.completion` | Summed fallback when total cost is absent. |
| resource `service.name` | Metadata `service`. |
| resource `deployment.environment.name` | Metadata `environment`. |
| `gen_ai.request.model` or `llm.model_name` | Metadata `model`. |
| `agent.name` | Metadata `agent`. |
| `journeygraph.cohort` | Metadata `cohort`. |

Only scalar string, boolean, integer, and double `AnyValue` variants participate in these
mappings. Array, key-value-list, and bytes variants are not imported. Scope data, span events,
links, dropped-count fields, and unknown attributes are ignored.

Recognizing `openinference.span.kind` and selected legacy `llm.*` attributes is not a claim of
OpenInference, Langfuse, Phoenix, or collector-wide compatibility. Users should validate a
representative sanitized export before relying on this experimental path.

### Upstream OTLP references

The importer boundary was checked against these primary sources:

- [OTLP specification and JSON protobuf encoding](https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding)
- [`ExportTraceServiceRequest` protobuf definition, OTLP v1.10.0](https://github.com/open-telemetry/opentelemetry-proto/blob/v1.10.0/opentelemetry/proto/collector/trace/v1/trace_service.proto)
- [`Span`, `SpanKind`, and `Status` protobuf definitions, OTLP v1.10.0](https://github.com/open-telemetry/opentelemetry-proto/blob/v1.10.0/opentelemetry/proto/trace/v1/trace.proto)
- [OpenTelemetry GenAI semantic conventions repository](https://github.com/open-telemetry/semantic-conventions-genai)
- [OpenInference semantic conventions](https://arize-ai.github.io/openinference/spec/semantic_conventions.html)
- [OpenInference semantic-conventions 0.1.31 package provenance](https://pypi.org/project/openinference-semantic-conventions/0.1.31/)

Actual committed-shape evidence is pinned separately in the
[instrumented test-data harness](../test-data/README.md). A fixture proves only the exact
emitted and tested shape recorded in its provenance sidecar.

Upstream semantic conventions evolve independently. JourneyGraph supports only the mappings
listed above; a linked upstream field is not automatically supported.

## Ordering and duplicates

Events are grouped by `trace_id` and sorted by:

1. exact normalized UTC timestamp;
2. `step_id` as a deterministic tie-breaker.

Original parent relationships are diagnostic. A parent timestamp later than its child emits
a warning; it does not reorder the trace. Missing and cross-trace parents, multiple roots,
and disconnected structures produce warnings. Parent cycles are errors.

For OTLP/JSON, the resulting paths and transitions are chronological adjacency, not reconstructed
parent-aware control flow. Sibling or concurrent spans can be adjacent after timestamp sorting
without representing a sequential transition. The importer emits an
`otlp_chronological_adjacency` warning on every accepted OTLP dataset.

An exact duplicate `(trace_id, step_id)` event is removed with a warning. Two different events
with the same identity are a blocking validation error.

## Outcome reconciliation

Each trace has one outcome bucket:

1. The latest chronological explicit event outcome wins.
2. Without an explicit business outcome, the trace becomes `unknown` regardless of terminal
   event or span status.

The missing case emits a `missing_outcome` warning. `status: error` remains available as a
technical error event and failure-point signal, but it does not establish a business failure.
An earlier error does not override a later explicit success, so retry-then-success remains
successful. `failure`, `dropoff`, and `handoff` require an explicit outcome value.

## Analysis schema

`analysis.json` is a UTF-8 JSON object with `schema_version: "1.2"`. The packaged
[`analysis-v1.schema.json`](../src/journeygraph/schemas/analysis-v1.schema.json) describes the
complete record shapes and required fields. Its public top-level sections are:

| Section | Meaning |
| --- | --- |
| `tool_version` | JourneyGraph package version that produced the payload. |
| `config` | Meaning-changing options, currently the cohort key. |
| `totals` | Input records, accepted events, traces, nodes, transitions, unique transitions, paths, and warnings. |
| `outcomes` | Reconciled outcome `counts` and trace-level `rates`. |
| `nodes` | Stable node IDs, labels, categories, event counts, trace counts, `error_event_count`, per-category `metrics` (`duration_ms`, `total_tokens`, `cost_usd`), and `trace_outcomes` of the traces that visit the category. |
| `transitions` | Source/target IDs and labels, chronological-adjacency `weight`, distinct `trace_count`, and `trace_outcomes` of the traces that contain the transition. |
| `entries`, `terminals` | First and last node counts across traces. |
| `paths` | Exact chronological node-ID and label sequences, frequency, outcomes, and success comparison; path records do not contain latency, token, or cost metrics. |
| `retries` | Adjacent exact-category repetitions, occurrence count, and trace count. |
| `loops` | Exact non-adjacent return sequences, occurrence count, and trace count. |
| `failure_points` | Technical error-event and explicit terminal-failure locations. |
| `dropoff_points` | Terminal traces with an explicit `dropoff` outcome; historical source fields remain schema-compatible. |
| `path_comparison` | Successful versus non-successful trace and path counts. |
| `cohorts` | Configured metadata key, missing/conflicting counts, per-value outcomes, and per-value event-level metrics. |
| `metrics` | Global event-level duration, token, and cost summaries. |
| `warnings` | Stable structured data-quality and privacy issues. |
| `findings` | `config` (`min_support`, `max_items`) and up to ten ranked association-only `items`. |
| `path_variants` | Traces grouped after collapsing consecutive repeated blocks: `variant_id`, `steps` (`node_ids`, `labels`, `repeated`), `trace_count`, `rate`, `path_count`, merged `path_ids`, and `trace_outcomes`. |
| `sequence_patterns` | Up to 50 contiguous two- and three-category sequences over retry-collapsed paths present in at least `min_support` traces: `pattern_id`, `node_ids`, `labels`, `length`, `trace_count`, `trace_outcomes`. |
| `filters` | Applied `outcomes`, `since`, `until` (UTC strings or `null`), `input_trace_count`, and `retained_trace_count`. |

Metric summaries contain `count`, `missing_count`, `sum`, `min`, `max`, `mean`, `p50`, `p95`,
and `percentile_method`. Missing values are not interpreted as zero, except that combined
tokens add the present input/output side when only one side exists. A combined token value is
missing only when both sides are missing.

### Findings

Each finding item has `kind`, `node_id`, `pattern_id`, `label`, `labels`, `support`, `baseline_support`, `value`,
`baseline`, `effect`, `interval`, `support_level`, and a fixed-template English `statement`.
`interval` is a two-sided 95% Wilson score interval for `value` or `null`. `support_level` is
`low` when `support` or `baseline_support` is below 10.

| Kind | Eligibility (with `min_support`, default 3) | Emitted when |
| --- | --- | --- |
| `outcome_association` | At least `min_support` known-outcome traces visit the category and at least `min_support` do not. | The success rates differ by at least 0.20. `value` is the visiting rate, `baseline` the non-visiting rate. |
| `sequence_association` | Same as `outcome_association`, for a published sequence pattern. `node_id` is `null`, `pattern_id` and `labels` identify the sequence. Skipped when one of its categories already has an `outcome_association` with the same support; sequences with identical counts and rates are reported once (shortest first). | The success rates differ by at least 0.20. |
| `error_hotspot` | At least `min_support` events. | At least 20% of the category's events have status `error`; `baseline` is the dataset-wide rate. |
| `duration_concentration` | At least two categories, at least `min_support` present durations. | The category holds at least 25% of summed `duration_ms`. For OTLP input this is a share of summed span durations, not wall-clock time. |
| `cost_concentration` | At least two categories, at least `min_support` present costs. | The category holds at least 25% of supplied `cost_usd`; missing cost values are stated. |
| `retry_prevalence` | Adjacent repetitions in at least `min_support` traces. | Repetitions occur in at least 10% of traces. |

Success rates use only traces with a known outcome; `unknown` traces are excluded and the
statement says how many were excluded. Items are ranked by kind in the order above, then by
`effect` descending, `support` descending, and `node_id`; only the first ten are published.

Variant rule: scanning left to right, the shortest block of one to four categories that is
immediately repeated is collapsed into one step with `repeated: true`; otherwise one category
becomes a step with `repeated: false`. Variant and sequence IDs hash
`["journeygraph.variant/v1", [repeated, node_id, ...], ...]` and
`["journeygraph.sequence/v1", node_id, ...]` with the same compact JSON encoding as other IDs.

Migration from 1.1: `path_variants`, `sequence_patterns`, and `filters` are new required
sections; finding items gained `pattern_id` and `labels`, and `node_id` may be `null` for
sequence findings. All other 1.1 keys, identities, and orderings are unchanged.

Migration from 1.0: all 1.0 keys, identities, and orderings are unchanged. Strict validators
pinned to the 1.0 schema must update, because nodes, transitions, and the top level gained
required fields. Readers that ignore unknown fields need no change.

The schema contains no generation timestamp, random identifier, absolute input path, or raw
input content. Labels and allowlisted metadata remain user data and may still be sensitive.
