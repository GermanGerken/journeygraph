# Instrumented Trace Test-Data Harness ExecPlan

This living plan establishes reproducible evidence for JourneyGraph's existing experimental
OTLP/JSON importer. It does not expand product compatibility, add collection to JourneyGraph,
or treat demo or synthetic data as production traces.

## Purpose and observable outcome

The repository currently tests a manually authored representative OTLP request. The goal is to
add small publishable fixtures that were actually emitted by OpenTelemetry/OpenInference SDKs,
captured through a local OpenTelemetry Collector, sanitized deterministically, and rejected by
automation if provenance or disclosure checks fail.

The completed repository should contain:

- a pinned Collector with an OTLP/HTTP receiver and JSON file exporter;
- a pinned official `open-telemetry/opentelemetry-demo` capture workflow;
- offline OpenInference scenarios using the official instrumentation package and standard OTLP;
- a deterministic raw-file-exporter JSONL to one-request OTLP/JSON preparation step;
- strict structural, provenance, secret, sensitive-key, PII-pattern, and local-path checks;
- separate committed golden/integration fixtures and ignored raw/private/external corpora;
- tests for observed importer and analytical invariants, not merely successful decoding;
- exact reproduction, update, publication, and private-intake instructions.

## Verified starting state

Verified on 2026-08-01 against `origin/main` commit
`22a1e806ad843baa7ccc9fa695627dade305fe19`:

- OTLP import is explicit `--format otlp-json` and accepts one UTF-8, uncompressed JSON
  `ExportTraceServiceRequest`; Collector file-exporter JSONL is not accepted directly.
- The hierarchy is `resourceSpans[].scopeSpans[].spans[]`. A span requires non-zero hex
  trace/span IDs, a non-empty name, and Unix-nanosecond start/end values. Parent ID, numeric
  kind, numeric status, resource/scope detail, and attributes have the documented narrow rules.
- Scalar string, bool, int, and double `AnyValue` variants decode. Array, kvlist, and bytes are
  accepted but ignored by current mappings. Unknown fields and attributes are ignored.
- OpenInference support is a mapping subset, not producer-wide compatibility. The importer
  keeps selected kind, component, token, cost, outcome, and operational metadata fields.
- Normalization sorts by timestamp then span ID. Parent relationships produce diagnostics but
  do not define control flow. Missing explicit business outcome remains `unknown`.
- Exact duplicate event identities are deduplicated with a warning; conflicting duplicate
  identities fail. Missing parents and incomplete structures warn.
- The committed OTLP fixture is hand-authored. No fixture has per-file provenance, capture
  instructions, or content-aware disclosure checks.
- Product metadata filtering is deliberately key-based and cannot prove a fixture is safe to
  publish.

## Scope and non-goals

In scope are test-data tooling, repository-only dependencies isolated from the runtime package,
fixtures, tests, Make targets, documentation, and the minimum documentation-check integration.

Out of scope are a live receiver inside JourneyGraph, OTLP/gRPC or protobuf-binary import,
direct Collector JSONL import, generic JSON auto-detection, new semantic mappings, parent-aware
control-flow reconstruction, outcome inference, cloud backends, paid model calls, and
production-derived fixtures without separate permission and disclosure review.

## Pinned upstreams

- OpenTelemetry Demo tag `3.0.0`, commit
  `1755859a9de82c2e5e225be68abc401a5ebf2b4f` (Apache-2.0).
- OpenTelemetry Collector Contrib image `0.157.0`; release tag commit
  `07bea6693ca67f7ce33c03502749c772d0d3c56b` (Apache-2.0).
- `openinference-instrumentation==0.1.56` and
  `openinference-semantic-conventions==0.1.31` (Apache-2.0), with the Python OpenTelemetry SDK
  and OTLP/HTTP exporter pinned in the generation-only lock file.

Pins are evidence, not compatibility ranges. Updating any one requires regenerating fixtures,
reviewing the upstream license and emitted shape, and rerunning all corpus and product gates.

## Corpus tiers and publication boundary

1. `tests_integration/fixtures/otlp/golden/` contains the smallest deterministic CI cases.
2. `test-data/fixtures/integration/` contains small, sanitized, instrumented multi-trace samples
   used by the fuller integration contract.
3. `data/external-corpus/` is ignored and optional for larger local checks.
4. `test-data/raw/`, `test-data/work/`, and `data/private/` are ignored and never publishable.

Every committed OTLP fixture has a sidecar provenance record with source, exact version and
commit, capture date, commands, source license, classification, sanitization actions, content
digest, observed dimensions, limitations, and usage restrictions. Allowed classifications are
`synthetic`, `instrumented-demo`, and `production-derived`; this plan creates no
`production-derived` fixture.

## Sanitization contract

Preparation parses every Collector JSONL record, selects whole traces, and emits one canonical
request object without changing trace/span IDs or parent links. It shifts all timestamps by one
constant, preserving durations and relative order. It removes status messages, events, links,
trace state, HTTP/network payload detail, headers, cookies, credentials, prompt/response and
document content, tool arguments/results, and user/session identifiers. Only the documented
operational and OpenInference semantic allowlist survives. Labels are accepted only for pinned
demo sources or pseudonymized before publication.

The checker then reparses the fixture, validates IDs/references/timestamps/AnyValue structure,
compares its SHA-256 with provenance, and scans keys and serialized content for credential,
token, email, phone, personal identifier, absolute path, private-key, and prompt/document/tool
payload patterns. This is a strict accidental-disclosure guardrail, not a proof of anonymity.
Manual review remains required before publication.

## Fixture scenarios and invariants

The OpenInference sample covers a simple LLM workflow, one and multiple tool calls, overlapping
sibling tools, tool failure, retry then success, agent handoff, explicit success/failure, and a
completed capture with no business outcome representing an incomplete workflow. It uses fixed
IDs and times for deterministic generation; model and tool results are synthetic and contain no
provider call.

The official Demo sample must include parent-child spans and multiple services. Selection
prefers traces that collectively add sibling overlap, errors, and raw-export ordering ambiguity.
If the captured run does not contain all preferred properties, provenance and documentation
must state the missing property rather than invent it.

Tests assert multiple resources/scopes, out-of-order input normalization, sibling concurrency,
missing parents/outcomes, error status, incomplete traces, exact and conflicting duplicate IDs,
protobuf JSON timestamps, scalar and ignored composite `AnyValue` variants, unknown attributes,
and byte-stable repeated analysis. They explicitly prove that parent-child hierarchy is not
reported as chronological control flow and that missing outcome is `unknown`, not drop-off.

## Milestones

- [x] Audit importer, existing fixtures, privacy model, tests, and documentation.
- [x] Add pins, Collector configuration, capture/generation commands, and ignored data tiers.
- [x] Add deterministic fixture preparation, provenance, and disclosure checks.
- [x] Generate and validate the OpenInference fixture through the local Collector.
- [x] Capture, select, sanitize, and validate a small official Demo fixture.
- [x] Add importer/analysis invariants and corpus-check tests.
- [x] Document reproduction, updates, publication, and private trace intake.
- [x] Run focused tests and the complete `make verify` gate; record exact evidence.

## Risks and decisions

- **Collector output is JSONL, importer input is one JSON request.** The harness makes this
  conversion explicit; product support is unchanged.
- **Demo capture is resource-heavy and nondeterministic.** The source is pinned and the final
  selection/sanitization is deterministic. Exact timestamps are shifted; structural properties
  are recorded from the committed result.
- **OpenInference payload capture is risky by default.** Generation config hides inputs,
  outputs, messages, prompts, choices, tool definitions, and invocation parameters before
  export; the repository sanitizer and checker remain mandatory second and third gates.
- **No outcome convention is universal.** Only the synthetic `journeygraph.outcome` attribute
  supplies a business outcome. Its absence stays unknown.
- **A demo is not production evidence.** Both upstream samples are classified
  `instrumented-demo`; issue #5 real-export evidence remains open.
- **Working-copy access.** The original macOS `Documents/JourneyGraph` directory was unreadable
  to the execution shell (`Operation not permitted`). Work proceeds in a separate clone so an
  unknown dirty local tree is never overwritten. This must be reconciled before merge.

## Progress and outcomes

- 2026-08-01: Audited the exact importer, normalization semantics, current fixture/tests,
  privacy documentation, active plans, and upstream Collector/Demo/OpenInference sources.
- 2026-08-01: Confirmed Docker Engine 29.1.3 and Compose 5.0.1 are available and verified the
  pinned Collector image manifest.
- 2026-08-01: Generated 7 OpenInference traces / 17 spans through OTLP/HTTP and the pinned
  Collector. A second full generation produced the same fixture SHA-256
  `2a156e28b129ae319d782716f32ff6e4e16d4948d0f4068486b29f6d9e788337`.
- 2026-08-01: Captured the pinned official Demo checkout dependency closure through the local
  Collector. The selected 5 traces / 55 spans contain 9 services, 50 parent links, 2 technical
  error spans, concurrent siblings, source-order ambiguity, and no explicit business outcome.
  The quote service was started explicitly because checkout calls it without declaring a Compose
  dependency.
- 2026-08-01: Added two instrumented-demo fixtures and two synthetic golden/functional fixtures,
  all with validated provenance/digests. `make corpus-check` validates all four and rejects
  tracked raw/private/external-corpus paths.
- 2026-08-01: Focused Ruff, mypy, docs, corpus, and 32 unit/integration/functional tests passed.
  The first complete gate ran 191 tests at 93.32% combined statement/branch coverage and passed
  wheel smoke, then exposed only expected high-entropy OTLP IDs and digests in secret scanning.
  Those exact false positives were reviewed and recorded in the existing baseline without
  excluding fixture files from scanning.
- 2026-08-01: Final `make verify` passed: Ruff format/lint, strict mypy, 191 tests at 93.32%
  combined statement/branch coverage, source/wheel build and isolated wheel smoke,
  documentation and four-fixture corpus checks, dependency audit, Bandit, and tracked/untracked
  file secret scanning. The reviewed baseline was staged only during the local hook invocation
  and restored to an unstaged working-tree change afterward; no source change was left staged.

The two instrumented fixture families are actual emitted-and-captured evidence. They remain
demo/synthetic control workloads rather than production evidence, and neither establishes broad
OpenTelemetry Demo, Collector, OpenInference, framework, or provider compatibility.
