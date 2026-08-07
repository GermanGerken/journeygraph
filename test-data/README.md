# Instrumented OTLP Test Data

This directory is a repository-only evidence harness for JourneyGraph's experimental
OTLP/JSON importer. It produces small publishable fixtures from actual OpenTelemetry and
OpenInference instrumentation without adding runtime dependencies, a receiver, or a general
Collector-file format reader to JourneyGraph.

## Exact format boundary

The pinned Collector receives standard OTLP/gRPC or OTLP/HTTP and its file exporter writes
JSONL: one JSON-encoded `ExportTraceServiceRequest` per line. JourneyGraph does **not** accept
that Collector JSONL directly. `scripts/trace_corpus.py prepare` parses all lines, selects whole
traces, sanitizes them, and emits one uncompressed UTF-8 OTLP/JSON request object accepted only
with `--format otlp-json`.

Canonical JourneyGraph JSONL is a different format: each line is one
`journeygraph.event/v1` object. Do not rename Collector output or pass it as canonical JSONL.

## Corpus tiers

| Tier | Git policy | Purpose |
| --- | --- | --- |
| `tests_integration/fixtures/otlp/golden/` | committed | Minimal hand-authored contract and edge cases. |
| `test-data/fixtures/integration/` | committed | Small sanitized samples actually emitted by instrumented systems. |
| `data/external-corpus/` | ignored | Optional larger, already-authorized local test corpus. |
| `test-data/raw/`, `test-data/work/` | ignored | Raw Collector output, logs, generated code, and upstream checkout; never publishable. |
| `data/private/` | ignored | Separately authorized private evidence; never publishable by default. |

Every committed OTLP fixture has a `.provenance.json` sidecar with its source pin, license,
classification, generation description, sanitization record, SHA-256 digest, observed
dimensions, limitations, and usage boundary. `synthetic`, `instrumented-demo`, and
`production-derived` are distinct classifications. This repository currently contains no
production-derived fixture.

## Prerequisites and pins

Run `make setup` first. Reproduction also needs Docker Engine with Compose, Python 3.11 or
later, Git, and network access to fetch the generation-only Python packages, pinned container
images, and the pinned official Demo checkout. No API key, model account, paid call, or cloud
backend is used.

Exact source, package, release-commit, image, and image-digest pins live in `pins.env` and the
two generation-only requirements lock files. These pins are evidence for the committed samples,
not compatibility ranges.

## Reproduce the fixtures

The offline OpenInference scenarios use the official `openinference-instrumentation` tracer and
the standard OpenTelemetry Python OTLP/HTTP exporter. The instrumentation is configured to hide
inputs, outputs, messages, prompts, choices, tools, and invocation parameters before export.
The emitted results and control flow are deterministic synthetic values; no model or provider is
called.

```bash
make trace-openinference
```

This produces seven traces and seventeen spans covering simple LLM, single and overlapping
tool calls, tool failure, retry then success, agent handoff, explicit outcomes, and a workflow
whose exported spans end without a business outcome.

The official OpenTelemetry Demo workflow checks out tag `3.0.0` at its exact commit, starts the
dependency closure for the official checkout service plus the quote service, and makes direct
calls to the Demo's public cart/checkout gRPC API. It sends one expected empty-cart failure and
two successful checkouts. The client constructs synthetic example-only contact/payment values
at runtime; raw telemetry remains ignored.

```bash
make trace-demo
```

The Demo source and Collector images are relatively large. Pulls are bounded to four attempts
per image. The capture is nondeterministic, so regeneration can change the selected five whole
traces even though source and preparation are pinned. Review every diff and its recomputed
observed dimensions; never force it to resemble the existing fixture.

For isolated Collector inspection, use `make trace-collector-up` and
`make trace-collector-down`. The two full capture targets manage their own Collector lifecycle.

## Sanitization and publication gate

Preparation applies a constant timestamp shift, preserving relative order and duration. It
keeps trace/span IDs and parent links so hierarchy tests remain meaningful, but removes events,
links, status messages, trace state, non-allowlisted attributes, payload fields, headers,
cookies, credentials, user/session identifiers, infrastructure details, and content-bearing
prompt/response/document/tool fields.

```bash
make corpus-check
```

The offline gate reparses every committed fixture, validates OTLP structure, IDs, references,
timestamps and `AnyValue` wrappers, checks sidecar shape and SHA-256, and scans keys and content
for common secrets, credentials, PII patterns, local absolute paths, and payload-bearing fields.
It also rejects tracked raw/private/external-corpus files. This is a strict accidental-
disclosure guardrail, not proof of anonymity; manual review is still mandatory.

To update a fixture:

1. update the exact upstream pin and review its license and release change;
2. regenerate only through the relevant capture target;
3. inspect the raw data locally without adding it to Git;
4. review the complete sanitized fixture and provenance diff;
5. run `make corpus-check`, focused corpus tests, and `make verify`;
6. describe only observed properties and limitations—never infer producer-wide compatibility.

## Private production intake

Do not place production traces in this harness. Private-analysis permission is not public-fixture
permission. Use the [privacy-safe real-trace discovery protocol](../docs/real-trace-discovery.md),
obtain explicit authority, minimize at the source, keep raw/working/output evidence in approved
encrypted storage, preserve only relationships needed for the question, and require separate
permission plus independent disclosure review before deriving any public fixture. Missing
business outcome must remain `unknown`; it must not be relabeled as drop-off or failure.
