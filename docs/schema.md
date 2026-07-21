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

## Experimental OTLP/JSON import

OTLP/JSON import is experimental and must be selected explicitly:

```bash
journeygraph validate export.json --format otlp-json
```

The importer accepts one uncompressed JSON-encoded OTLP/HTTP
`ExportTraceServiceRequest` body with this hierarchy:

```text
resourceSpans[].scopeSpans[].spans[]
```

It follows the official lowerCamelCase JSON field names, hexadecimal trace/span identifiers,
integer enum encoding, protobuf `AnyValue` wrappers, and Unix-nanosecond timestamps. It is
not a receiver, collector, live exporter, gRPC decoder, protobuf-binary decoder, gzip decoder,
or generic JSON trace importer.

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
- [OpenInference semantic-conventions 0.1.30 package provenance](https://pypi.org/project/openinference-semantic-conventions/0.1.30/)

Upstream semantic conventions evolve independently. JourneyGraph supports only the mappings
listed above; a linked upstream field is not automatically supported.

## Ordering and duplicates

Events are grouped by `trace_id` and sorted by:

1. exact normalized UTC timestamp;
2. `step_id` as a deterministic tie-breaker.

Original parent relationships are diagnostic. A parent timestamp later than its child emits
a warning; it does not reorder the trace. Missing and cross-trace parents, multiple roots,
and disconnected structures produce warnings. Parent cycles are errors.

An exact duplicate `(trace_id, step_id)` event is removed with a warning. Two different events
with the same identity are a blocking validation error.

## Outcome reconciliation

Each trace has one outcome bucket:

1. The latest chronological explicit event outcome wins.
2. Without an explicit outcome, terminal `status: error` becomes `failure`.
3. Any other trace without an explicit outcome becomes `dropoff`.

The inferred cases emit `missing_outcome` warnings. An earlier error does not override a later
explicit success, so retry-then-success remains successful.

## Analysis schema

`analysis.json` is a UTF-8 JSON object with `schema_version: "1.0"`. The packaged
[`analysis-v1.schema.json`](../src/journeygraph/schemas/analysis-v1.schema.json) describes the
complete record shapes and required fields. Its public top-level sections are:

| Section | Meaning |
| --- | --- |
| `tool_version` | JourneyGraph package version that produced the payload. |
| `config` | Meaning-changing options, currently the cohort key. |
| `totals` | Input records, accepted events, traces, nodes, transitions, unique transitions, paths, and warnings. |
| `outcomes` | Reconciled outcome `counts` and trace-level `rates`. |
| `nodes` | Stable node IDs, labels, categories, event counts, and trace counts. |
| `transitions` | Source/target IDs and labels, adjacency `weight`, and distinct `trace_count`. |
| `entries`, `terminals` | First and last node counts across traces. |
| `paths` | Exact node-ID and label sequences, frequency, outcomes, and success comparison; path records do not contain latency, token, or cost metrics. |
| `retries` | Adjacent exact-category repeats, occurrence count, and trace count. |
| `loops` | Exact non-adjacent return sequences, occurrence count, and trace count. |
| `failure_points` | Error-event and reconciled terminal-failure locations. |
| `dropoff_points` | Terminal drop-offs with explicit/inferred source counts. |
| `path_comparison` | Successful versus non-successful trace and path counts. |
| `cohorts` | Configured metadata key, missing/conflicting counts, per-value outcomes, and per-value event-level metrics. |
| `metrics` | Global event-level duration, token, and cost summaries. |
| `warnings` | Stable structured data-quality and privacy issues. |

Metric summaries contain `count`, `missing_count`, `sum`, `min`, `max`, `mean`, `p50`, `p95`,
and `percentile_method`. Missing values are not interpreted as zero, except that combined
tokens add the present input/output side when only one side exists. A combined token value is
missing only when both sides are missing.

The schema contains no generation timestamp, random identifier, absolute input path, or raw
input content. Labels and allowlisted metadata remain user data and may still be sensitive.
