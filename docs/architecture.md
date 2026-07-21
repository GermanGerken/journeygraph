# Architecture

JourneyGraph is a local command-line and Python toolkit for deterministic analysis of
existing trace and event exports. It does not collect traces, run a server, call a model, or
send telemetry.

## Design goals

- Keep ingestion adapters separate from the vendor-neutral domain model.
- Keep graph construction and analytics pure, deterministic, and explainable.
- Treat privacy filtering as an input-boundary responsibility.
- Isolate filesystem effects in readers, artifact publication, and CLI orchestration.
- Use the Python standard library for the analytical core.
- Preserve enough structured detail for users to reproduce every aggregate.

JourneyGraph intentionally does not include a hosted service, authentication, billing,
real-time collection, a graph database, clustering, prediction, causal attribution, or an
LLM-based judge.

## Data flow

```text
local file
  -> format reader
  -> source records with safe locations
  -> validation, normalization, ordering, and metadata filtering
  -> immutable canonical events and traces
  -> aggregate graph
  -> deterministic analytics
  -> JSON, normalized JSONL, static HTML, and SVG renderers
  -> guarded local filesystem publication
```

The data flow above is one-way. The package dependency shape is deliberately different:

```text
CLI -> API -> ingestion ------> domain
        |  -> normalization --> domain
        |  -> analytics ------> graph
        |  -> reporting ------> normalization/domain
        +----------------------> shared exceptions/version
```

`journeygraph.domain` contains the shared immutable contracts. Importers may create source
records, but they do not make analytical decisions. Reporting consumes the analysis payload;
it does not recalculate paths, outcomes, or graph weights. The graph layer uses structural
protocols rather than importing provider or ingestion types.

## Package responsibilities

### `journeygraph.ingestion`

Readers decode local files into `SourceRecord` values. A source record holds a mapping, a
safe location such as a line or row number, its source sequence, and an optional exact
nanosecond timestamp. Readers report format and I/O errors but leave canonical validation to
normalization.

Implemented readers are:

- canonical JSON Lines;
- canonical CSV;
- optional canonical Parquet through PyArrow;
- an experimental, narrow OTLP/HTTP JSON trace-request importer.

OTLP/JSON is an adapter into the canonical schema. No tracing provider or framework type is
allowed into the downstream domain or analytical layers.

### `journeygraph.normalization`

Normalization is the trust boundary. It validates identifiers, timestamps, categories,
labels, numbers, statuses, outcomes, duplicate identities, and parent relationships. It
filters metadata before constructing `CanonicalEvent` values.

Accepted events are grouped by `trace_id` and ordered by exact normalized UTC timestamp,
then `step_id`. Parent relationships produce diagnostics but never silently override the
chronological order. Exact duplicate `(trace_id, step_id)` events are removed; conflicting
duplicates are errors.

The latest explicit event outcome becomes the trace outcome. Without one, a terminal error
becomes `failure`; any other terminal state becomes an inferred `dropoff`. Earlier errors do
not override a later explicit success.

### `journeygraph.domain`

The public domain values are frozen dataclasses:

- `SourceRecord`: decoded input plus a safe source location;
- `CanonicalEvent`: one validated, privacy-filtered operation;
- `Trace`: an ordered tuple of events and one reconciled outcome;
- `NormalizedDataset`: accepted events, traces, warnings, input format, and input count;
- `Issue`: a structured warning or validation error.

Mutable input mappings are not passed through the analytical core. Canonical metadata is
exposed as a read-only mapping.

### `journeygraph.graph`

An aggregate node represents the exact category `(operation_type, component)`, not an
individual event or span. Its display label is `operation_type:component`.

Node IDs are the lowercase hexadecimal SHA-256 digest of the compact UTF-8 JSON array:

```json
["journeygraph.node/v1","operation_type","component"]
```

An edge represents one ordered adjacent event pair. `weight` is the total number of observed
adjacencies; `trace_count` is the number of distinct traces containing that edge. Every
adjacent pair contributes to exactly one edge weight.

Exact path IDs hash the ordered node-ID sequence using the same versioned representation:

```json
["journeygraph.path/v1","first-node-id","second-node-id"]
```

Nodes and edges are sorted by identity before publication. Input trace order therefore does
not affect the aggregate graph.

### `journeygraph.analytics`

The analysis payload has schema version `1.0`. It contains totals, reconciled outcome counts
and rates, nodes, transitions, entries, terminals, exact paths, retries, loops, failure and
drop-off points, success versus non-success comparisons, cohorts, metric summaries, and
structured warnings.

Definitions are deliberately narrow:

- A **path** is the complete ordered sequence of aggregate node IDs for one trace.
- A **retry** is an adjacent repetition of the same exact node category.
- A **loop** is a non-adjacent return to the most recently visited matching node. The exact
  sequence from the previous occurrence through the return is counted. Adjacent retries are
  excluded from loops.
- A **failure point** includes an event whose status is `error`. A terminal node with a
  reconciled failure is also represented if it did not itself have error status.
- A **drop-off point** is the terminal node of a trace whose outcome is `dropoff`; explicit
  and inferred sources remain distinguishable.
- A **cohort** groups traces by the first chronological retained value for the configured
  metadata key. Missing and conflicting per-trace values are counted explicitly.

Metrics summarize present event-level duration, input tokens, output tokens, combined tokens,
and cost. Missing observations are excluded from sums, means, extrema, and percentiles and
are reported separately. Percentiles use the one-indexed nearest-rank definition.

These are descriptive associations. They do not establish causes, predictions, or ground
truth clusters.

### `journeygraph.reporting`

Reporting serializes the already-computed payload and renders:

- deterministic, UTF-8 `analysis.json`;
- deterministic, canonical `normalized.jsonl`;
- a static, escaped `report.html` with no executable JavaScript or remote dependency;
- an escaped standalone `graph.svg`.

The HTML embeds analysis data in a non-executable JSON block and applies a restrictive
Content Security Policy. SVG output contains no script, foreign object, event-handler
attribute, or remote resource.

### `journeygraph.api` and `journeygraph.cli`

The Python API composes reading, normalization, analytics, and artifact publication. The CLI
is a thin `argparse` boundary that maps expected failures to stable exit codes and prints
ordinary errors without a traceback.

Pure graph and analytics functions do not read files, inspect environment variables, print,
or use the network. Readers, writers, and CLI orchestration own product-path side effects.

## Determinism

For the same accepted input and configuration, analytical meaning is stable because:

- timestamps are normalized to UTC and ordered with an exact nanosecond value when present;
- `step_id` breaks equal-timestamp ties;
- traces, nodes, transitions, paths, loops, cohorts, and warnings use stable sort keys;
- node, path, loop, and cohort identities use versioned SHA-256 input representations;
- serialization sorts mapping keys;
- no generation timestamp, random identifier, absolute input path, or environment value is
  included in the analysis payload.

Warnings about original row order can differ when equivalent input rows are permuted. The
normalized events and analysis, excluding source-order diagnostics and raw input counts,
retain equivalent meaning.

## Failure boundaries

Malformed formats and invalid canonical fields block artifacts. Accepted data-quality and
privacy observations remain structured warnings. Artifact content is fully rendered before
publication, and each file is replaced atomically where the operating system supports it.
The set of several output files is not a transactional filesystem operation; an I/O failure
during publication can leave a subset of individually complete files.

## Extension rules

New format support belongs in `journeygraph.ingestion` and must translate into the existing
canonical schema. It must not add provider-specific branches to graph or analytics code.
Changes to event meaning, ordering, IDs, outcome reconciliation, privacy policy, or analysis
schema require an approved execution plan, independent test oracles, migration notes, and an
explicit versioning decision.
