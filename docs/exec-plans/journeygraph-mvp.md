# JourneyGraph v0.1 MVP ExecPlan

This is a living execution plan. It is intentionally self-contained: an engineer should be
able to resume the MVP using this file and the repository alone. Update `Progress`,
`Discoveries`, `Decision log`, and `Outcomes and retrospective` whenever implementation
evidence changes.

## Purpose and observable user outcome

JourneyGraph v0.1 will be a local-first Python toolkit that turns a collection of AI-agent
spans or generic events into a deterministic aggregate journey graph. It does not collect
traces. A user supplies an existing export, runs a command, and receives:

- a normalized, privacy-filtered event file;
- a versioned machine-readable analysis;
- a self-contained HTML report;
- a standalone SVG graph.

The observable MVP promise is:

> Local-first graph analytics for AI agent traces. Find recurring paths, loops, failures,
> and success patterns across OpenTelemetry and event data.

A fresh checkout must support a five-minute path from installation to a real report:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
journeygraph demo --output-dir journeygraph-demo
```

Core analysis makes no network request, requires no account, database, API key, LLM,
prompt, response, or document body, and emits no telemetry.

## Authorization and planning status

Repository guidance normally requires owner approval after this plan is written. The owner
explicitly approved creation and execution of this plan in the 2026-07-21 MVP task, without
a second approval stop. That authorization covers a local feature branch, repository edits,
project-local dependency installation, quality checks, demos, and logical local commits. It
does not authorize push, merge, release, tag, publication, remote settings changes, external
services, destructive actions, or edits outside JourneyGraph.

## Repository orientation and verified current state

Verified on 2026-07-21 before implementation:

- Canonical repository: `/Users/germangerken/PycharmProjects/journeygraph`.
- Remote: `origin = https://github.com/GermanGerken/journeygraph.git`.
- Default branch: `main`.
- Baseline: `e5e539fdde39fac1a810e166e3c5d64d32b7281c` (`chore: initialize
  JourneyGraph repository`).
- `main` was clean, tracked `origin/main`, and had no untracked files.
- No tags existed and history contained one commit.
- The implementation branch is `feat/journeygraph-mvp`.
- Because the execution sandbox only permits writes under the active workspace, the branch
  is checked out as a linked Git worktree at
  `/Users/germangerken/Documents/JourneyGraph/journeygraph`. The worktree shares branch and
  commit metadata with the canonical repository and leaves the `main` checkout unchanged.
- Initial tracked files were `.gitignore`, `AGENTS.md`, `LICENSE`, `README.md`,
  `docs/product-brief.md`, and `docs/exec-plans/README.md`.
- The license is Apache License 2.0. No `NOTICE` or third-party attribution file was required
  by the initial contents.
- The repository had no package metadata, application code, tests, CI, release harness, or
  implemented compatibility claims.

Read completely before planning: `AGENTS.md`, `README.md`, `docs/product-brief.md`,
`docs/exec-plans/README.md`, the license, Git status/history/remotes, and the Testing,
Coverage, Commands, and Completion Checklist guidance in the CyberBrain reference. The
reference was used only for reusable quality principles: black-box functional tests through
real entrypoints, Arrange/Act/Assert, real subprocess/filesystem behavior, negative paths,
coverage as a guardrail, and exact completion commands. CyberBrain-specific HTTP,
ClickHouse, settings, service architecture, paths, and deployment rules are not part of this
project.

## Assumptions

1. Python 3.11 and later are the supported runtimes for v0.1. The CI matrix will test every
   version declared in package metadata. Python 3.11 supplies `tomllib`, modern typing, and a
   practical maintenance floor without requiring a compatibility dependency.
2. Generic JSON Lines and CSV are the stable canonical input formats. Parquet is supported
   through an explicit optional dependency so the default installation remains small.
3. The single vendor/standard import path is OTLP/JSON trace export in the official
   OpenTelemetry protobuf JSON shape. It is an importer, not a claim of compatibility with
   every collector, backend, Langfuse export, Phoenix export, or OpenInference deployment.
4. Exact path grouping is more explainable than clustering for v0.1. No community detection,
   opaque ML, or prediction is included.
5. Missing explicit terminal outcomes describe incomplete journeys and are reported as
   `dropoff`, except a terminal error which is reported as `failure`. This is a descriptive
   rule, not causal attribution.
6. Event order is chronological by normalized UTC timestamp with `step_id` as the deterministic
   tie-breaker. Parent relationships are validated and used for data-quality diagnostics but
   do not silently reorder contradictory timestamps.
7. Exact duplicate `(trace_id, step_id)` records are deduplicated. Conflicting records with
   the same identity are errors. This makes re-import idempotent without hiding disagreement.
8. Metadata is denied by default except for a short operational allowlist. CLI additions to
   the allowlist cannot override a permanent sensitive-key denylist.

## Architecture

The package uses conventional `pyproject.toml` packaging and a `src/` layout. Boundaries are
directional:

```text
format file -> ingestion -> normalization -> domain traces -> graph -> analytics
                                                               |          |
                                                               + reporting+
                                                                      |
CLI/public API ------------------------------------------------ orchestration
```

- `journeygraph.domain`: frozen typed models for an event/span, trace/session, ordered path,
  aggregate graph, cohort/segment, outcome, issue, and report contracts.
- `journeygraph.ingestion`: readers for JSONL, CSV, optional Parquet, and OTLP/JSON. Readers
  return source records with locations and do not contain analytics.
- `journeygraph.normalization`: boundary validation, UTC conversion, finite numeric checks,
  deterministic ordering, duplicate policy, relationship checks, and metadata filtering.
- `journeygraph.graph`: pure aggregate node and transition construction.
- `journeygraph.analytics`: pure path, transition, loop, retry, failure, drop-off, cohort,
  latency, token, and cost summaries.
- `journeygraph.reporting`: deterministic JSON serialization plus escaped HTML and SVG
  rendering. Filesystem publication is atomic where practical.
- `journeygraph.api`: documented composition functions for integration users.
- `journeygraph.cli`: thin `argparse` orchestration and stable exit-code/error mapping.

The analytical core will use the standard library. It will not be coupled to a dataframe,
graph, web, templating, CLI, or tracing-vendor framework. PyArrow is an optional format
adapter only. Test and quality tools are development dependencies, not runtime requirements.

Pure transformations do not read files, inspect environment variables, print, or call the
network. Input readers, artifact publication, and the CLI own side effects.

## Canonical schema

### Concepts that must remain distinct

- **Event/span**: one timestamped operation within a trace. A span is one possible source
  representation of a canonical event.
- **Trace/session**: an ordered collection of canonical events sharing `trace_id`.
- **Ordered path**: the sequence of normalized operation categories for one trace.
- **Aggregate transition graph**: categories aggregated into weighted directed nodes/edges
  across traces. It is not a trace tree.
- **Cohort/segment**: traces grouped by one allowlisted operational metadata value. A cohort
  is not a path and does not imply cause.

### Event schema `journeygraph.event/v1`

Canonical JSONL contains one object per line with these fields:

| Field | Required | Contract |
| --- | --- | --- |
| `schema_version` | yes | Literal `1.0`. |
| `trace_id` | yes | 1–128 safe identifier characters; stable within a session. |
| `step_id` | yes | 1–128 safe identifier characters; unique within a trace. |
| `parent_step_id` | no | Same identifier rules; null/empty means no known parent. |
| `timestamp` | yes | RFC 3339 timestamp with offset; output normalized to UTC `Z`. |
| `operation_type` | yes | 1–64 safe category characters. Known values are documented; unknown valid values are preserved with a warning. |
| `component` | yes | Non-empty operational label, at most 256 Unicode characters. |
| `duration_ms` | yes | Finite non-negative number. |
| `status` | yes | `unset`, `ok`, or `error`. |
| `outcome` | no | `success`, `failure`, `handoff`, `dropoff`, or `unknown`. |
| `input_tokens` | no | Non-negative integer. |
| `output_tokens` | no | Non-negative integer. |
| `cost_usd` | no | Finite non-negative decimal number. |
| `metadata` | no | String/number/boolean/null values retained only for allowlisted keys. |

CSV uses the same scalar columns and `metadata.<key>` columns. Parquet uses the same logical
columns, with `metadata` as a mapping when available. The normalized export is canonical
JSONL with sorted keys and stable ordering.

Default retained metadata keys are operational and intentionally few: `agent`, `cohort`,
`environment`, `model`, `region`, `service`, `version`, and `workflow`. Unknown keys are
excluded and produce privacy/data-quality warnings. Permanently sensitive key fragments
include prompt, response, message content, document/body, email, authorization, token/secret,
API key, password, cookie, and common personal identifiers. These are excluded even if a
user attempts to allowlist them.

### Trace and outcome rules

Events are grouped by `trace_id` and sorted by `(timestamp_utc, step_id)`. The latest explicit
event outcome defines the trace outcome. Without one, a terminal `error` status means
`failure`; otherwise the trace is an inferred `dropoff`. An error earlier in a trace does not
override a later explicit success, so retry-then-success remains successful. Every trace has
exactly one final outcome bucket for reconciliation.

### Node, edge, path, and cohort identity

A graph node represents the tuple `(operation_type, component)`. Its public ID is a stable
digest of that tuple; its human label is preserved separately. An edge represents adjacent
events in an ordered path. `weight` is the total observed adjacency count; `trace_count` is
the number of distinct traces containing the edge. Path identity is the ordered sequence of
node IDs. Cohort identity is `(metadata_key, metadata_value)` after privacy filtering.

### Analysis schema `journeygraph.analysis/v1`

The deterministic JSON report includes:

- schema/tool versions and configuration that changes meaning;
- input, event, trace, and outcome totals;
- nodes and weighted transitions;
- entry and terminal node counts;
- exact paths with frequencies and outcome rates;
- retry counts for adjacent repeated categories;
- loops represented by a return to a previously visited category, grouped by exact loop
  sequence and counted per occurrence/trace;
- failure and inferred/explicit drop-off points;
- successful versus non-successful path counts, with handoff retained as its own outcome;
- cohort summaries for the configured allowlisted key;
- duration, token, and cost aggregates with documented missing-value counts;
- structured data-quality/privacy warnings.

No wall-clock generation timestamp, absolute input path, random identifier, or unstable map
ordering appears in deterministic analytical output.

## Validation and normalization policy

Ordinary input problems are collected into structured issues and rendered without a Python
traceback. Each issue states a code, severity, source location, problem, and corrective hint.
Values from sensitive fields are never echoed.

Errors block successful artifacts:

- missing required fields or malformed identifiers;
- invalid/non-offset timestamps;
- invalid status/outcome/schema version;
- negative, NaN, infinite, or wrongly typed numeric values;
- malformed JSONL/CSV/Parquet/OTLP structure;
- missing required CSV/Parquet columns;
- conflicting duplicate identities;
- parent cycles;
- empty input.

Warnings do not block analysis:

- exact duplicates removed;
- input rows arrived out of chronological order;
- equal timestamps used the `step_id` tie-breaker;
- missing or cross-trace parents;
- multiple roots/disconnected parent structure;
- parent timestamps later than child timestamps;
- missing explicit outcomes;
- valid but unknown operation types;
- excluded unknown or sensitive metadata;
- cardinality above the documented category threshold.

Normalization is a total deterministic transformation for accepted input. Permuting input
rows does not change normalized analytical meaning. Warnings are sorted and stable.

## OpenTelemetry import boundary

The OTLP/JSON reader accepts the official trace export hierarchy
`resourceSpans[].scopeSpans[].spans[]`, including protobuf JSON attributes and nanosecond
timestamps. It maps `traceId`, `spanId`, `parentSpanId`, start/end times, span name/kind,
status, and a small documented set of semantic/custom operational attributes. Resource and
scope fields remain importer context and are included only through the same metadata
allowlist. Unsupported signals and unknown attributes are ignored with safe warnings.

The fixture and docs will link the exact official OpenTelemetry protobuf and OTLP/JSON
sources verified during implementation. The project will claim only “OTLP/JSON trace import
(experimental)” in v0.1. It will not claim Langfuse, Phoenix, collector-wide, or
OpenInference compatibility without a tested documented export contract.

## Public Python API contract

The supported Python surface is intentionally small:

```python
from journeygraph.api import analyze_file, validate_file, write_analysis

dataset = validate_file("traces.jsonl", input_format="jsonl")
report = analyze_file("traces.jsonl", input_format="jsonl")
artifacts = write_analysis(report, "journeygraph-report")
```

Public dataclasses and exceptions are documented. Private module layout is not a stability
promise. Functional acceptance does not import this API; integration tests may.

## CLI contract

```text
journeygraph validate INPUT
    [--format auto|jsonl|csv|parquet|otlp-json]
    [--normalized-out PATH] [--allow-metadata-key KEY ...] [--force]

journeygraph analyze INPUT --output-dir DIR
    [--format auto|jsonl|csv|parquet|otlp-json]
    [--cohort-key KEY] [--allow-metadata-key KEY ...] [--force]

journeygraph demo [--output-dir DIR] [--force]
```

`validate` reports accepted event/trace counts and warnings; optional normalized output uses
the same privacy policy. `analyze` writes `analysis.json`, `normalized.jsonl`, `report.html`,
and `graph.svg`. `demo` writes the packaged deterministic synthetic dataset and analyzes it.
Input/output paths are explicit. A non-empty target or existing file is not overwritten
without `--force`. User-supplied paths containing `..`, symlink output roots, and collisions
with the input path are rejected. Files are rendered before publication and written through
temporary siblings with atomic replacement where the platform supports it.

Exit codes:

- `0`: success, including success with warnings;
- `1`: unexpected internal failure (concise message, no ordinary traceback);
- `2`: validation/format/usage error;
- `3`: input/output I/O failure;
- `4`: unsafe path or overwrite conflict.

`--help` exits zero and documents commands, formats, outputs, and exit behavior. Stable
messages are written to stdout; actionable errors are written to stderr.

## Reporting and untrusted content

`analysis.json` and `normalized.jsonl` are UTF-8 and deterministic. `report.html` is static,
works from `file://`, requires no server, account, database, network, or JavaScript, and
contains a restrictive Content Security Policy. All labels, metadata values, table cells,
SVG text, and embedded JSON escape untrusted content. Literal `<`, `>`, `&`, quotes, and
script-closing sequences cannot become executable markup. `graph.svg` also escapes XML and
contains no script, foreign object, remote link, or event-handler attribute.

The report explains that path/outcome relationships are associations, not causes. It shows
totals, frequent paths/transitions, graph, outcomes, retries/loops, failure/drop-off points,
cohorts, metrics, warnings, and limitations.

## Privacy and threat model

### Data processed

JourneyGraph reads operational identifiers, timestamps, operation/component labels, status,
outcome, durations, token/cost metrics, and explicitly allowlisted metadata from local files.
It generates local artifacts at the path selected by the user.

### Excluded by default

Raw prompts, responses, messages, document contents, bodies, emails, personal identifiers,
authorization headers, API keys, passwords, cookies, secrets, and unknown metadata are not
needed and are not emitted. JourneyGraph has no telemetry and no network code in its product
path.

### Threats and controls

- **Sensitive-data propagation:** allowlist plus non-overridable sensitive denylist;
  downstream tests prove excluded values cannot reappear.
- **HTML/SVG injection:** contextual escaping, non-executable embedded data, CSP, no runtime
  templating or client script.
- **Accidental overwrite/path traversal:** fixed artifact names, `..` rejection, symlink-root
  rejection, collision checks, opt-in force, temporary writes.
- **Resource exhaustion:** bounded identifier/label lengths, clear format errors, streaming
  readers where practical, and a documented local performance scenario. v0.1 does not claim
  protection against hostile files designed to exhaust memory.
- **Dependency compromise:** standard-library core, optional PyArrow isolated to ingestion,
  pinned lock/check workflow, dependency audit, static security scan, and secret scan.

Redaction is key-based filtering, not a guarantee that an allowlisted value is anonymous.
Operational labels, IDs, cohort values, model/service names, timestamps, rare paths, and
small-group metrics may remain sensitive. Users must inspect artifacts, restrict filesystem
permissions, aggregate sufficiently, and avoid sharing reports as if they were anonymized.

## Dependency decisions

- Runtime core: Python standard library only, to minimize supply-chain and installation
  surface.
- Optional `parquet` extra: PyArrow, used only for real Parquet decoding and schema access.
  Its size and compiled distribution are why it is not mandatory.
- Development: pytest, pytest-cov/coverage, Hypothesis, Ruff, mypy, build, pip-audit, Bandit,
  detect-secrets, and mutmut. Each has one explicit quality role; none is imported by the
  installed runtime.

Before finalizing constraints, current versions, maintenance, supported Python versions, and
licenses will be verified from official project metadata/documentation. A lock file may be
committed for repeatable development; package metadata will use bounded compatible ranges
rather than an environment-specific frozen runtime.

## Testing architecture

Tests are delivered with behavior and use visually distinct Arrange, Act, Assert phases.
Warnings fail tests unless narrowly justified. Randomness, locale-sensitive formatting,
timezone, filesystem ordering, and generated timestamps are controlled.

### `tests_unit/`

Pure algorithms and edge cases: identifier/numeric/timestamp parsing, ordering, duplicate
policy, parent cycles, metadata filtering, category/path identity, transition counts, loop
detection, cohort/outcome aggregation, metric percentiles, serialization, HTML/XML escaping,
and property-based/metamorphic invariants. Unit tests localize faults but do not replace
public behavior.

### `tests_integration/`

Real component composition through documented public APIs: reader plus validation,
normalization plus graph, graph plus analytics, JSON/CSV/Parquet/OTLP formats, canonical
round-trips, JSON serialization, HTML/SVG reporting, and real temporary files. No network and
no mocking of pure production logic.

### `tests_functional/`

The acceptance backbone. Tests locate and execute the real installed `journeygraph` command
as a subprocess, supply real files, inspect real outputs, and assert exit/stdout/stderr
contracts. They never import `journeygraph` modules, construct domain objects, patch
production behavior, or duplicate its algorithms. JSON is parsed and checked semantically;
HTML is inspected with a parser; SVG/XML is parsed. Tests are meaningful if the CLI were
rewritten in another language.

Subprocess coverage is configured through Coverage.py's supported subprocess mechanism and
verified empirically. CI additionally builds a wheel, installs it in an isolated environment,
and runs help plus a complete demo without repository-relative imports.

## Black-box acceptance scenarios

Functional scenarios cover, with manually specified oracles:

1. Linear successful trace: validation, ordered path, transitions, terminal outcome, all
   four artifact types.
2. Branching success/failure: both paths, reconciled totals/rates, path comparison.
3. Retry then success: self-transition/retry count and final success.
4. Loop/repeated tool sequence: exact loop occurrence, no phantom edge, repeat determinism.
5. Repeated failure and handoff: failure point, distinct handoff, reconciled metrics.
6. Out-of-order and equal timestamps: documented sort/tie-break, byte-equivalent analysis.
7. Exact/conflicting duplicates: idempotent removal versus actionable blocking error.
8. Missing/malformed fields and formats: IDs, timestamps, status, duration, negative/NaN/
   infinity, malformed JSONL, required CSV/Parquet schema, malformed OTLP; no traceback or
   successful partial report.
9. Empty input: clear non-zero result and no misleading artifact.
10. Sensitive metadata: representative prompt, response, email, authorization, API key,
    password, cookie, and unknown nested fields absent from every artifact.
11. HTML/SVG injection: labels remain visibly escaped and non-executable.
12. Unsafe paths/overwrite: no overwrite without force, traversal/symlink rejection, no
    successful partial output after validation failure.
13. Unicode/portability: Cyrillic, accents, emoji, and long valid labels remain valid UTF-8.
14. OTLP/JSON representative fixture: documented fields map correctly, unsupported data does
    not leak.
15. Installed wheel: build/install/help/demo and packaged demo data work in isolation.

## Correctness oracles and invariants

Selected fixtures independently specify ordered label paths, node/edge sets, weights, entry
and terminal counts, loops/retries, outcomes, duration/token/cost totals, and privacy
exclusions. Expected values are not generated by production functions.

Required invariants:

- each adjacent event pair contributes exactly one transition;
- edge weight totals equal represented adjacent transition counts;
- entry and terminal totals each equal trace count;
- outcome buckets reconcile to total traces;
- exact-path frequencies reconcile to total traces;
- retry/loop counts are non-negative and trace counts do not exceed occurrence counts;
- missing metrics are excluded from sums/means and reported in missing counts;
- input permutation does not change normalized meaning or analysis;
- adding/removing an unrelated trace changes only its documented contributions;
- duplicate normalization is idempotent;
- canonical export/re-import preserves supported fields;
- unknown/sensitive metadata never reappears downstream;
- arbitrary escaped text cannot introduce executable HTML/SVG.

Hypothesis strategies remain bounded and deterministic enough for CI. A meaningful minimized
failure becomes a normal regression fixture before the defect is fixed.

## Coverage, mutation, and regression policy

Combined statement and branch coverage must be at least 90%, enforced rather than merely
reported:

```bash
python -m pytest tests_unit tests_integration tests_functional \
  --cov=journeygraph --cov-branch --cov-report=term-missing \
  --cov-report=xml --cov-fail-under=90
```

Normalization, graph construction, path/loop analysis, privacy, and serialization require
explicit positive and negative behavior tests regardless of headline coverage. No broad
exclusions, import-only tests, meaningless assertions, removed negative branches, or coverage
threshold reductions are acceptable.

Mutation testing targets deterministic ordering/deduplication, transition/path counts, loop
detection, outcomes, metadata filtering, and escaping. It may be a slower manual command but
must run once before MVP completion. Surviving mutations are reviewed; tests are added only
when they reveal a behavioral gap.

For each discovered user-visible defect: preserve the smallest reproducer, add and confirm a
failing functional regression first, implement the fix, run its surrounding layer, then run
full verification. Do not hide flakes with reruns. Run the full suite at least twice before
completion to expose order dependence.

## Performance strategy

Provide a deterministic synthetic generator/benchmark that separately reports ingestion,
normalization, graph, analytics, report rendering, and peak memory when practical. The local
developer scenario will use thousands of traces and enough repeated/branching structure to
detect obvious quadratic regressions while remaining quick. Record hardware/runtime/dataset
size with measured results. Do not advertise a universal time threshold or benchmark claim
from one machine. Optimize only after profiling evidence.

## Repository harness and canonical commands

One `Makefile` is the canonical interface used locally and in CI:

```text
make setup          create/install the developer environment
make format         apply formatting
make format-check   verify formatting
make lint           run Ruff
make typecheck      run mypy
make test-unit      run unit tests
make test-integration
make test-functional
make coverage       enforce statement/branch threshold and write XML
make build          build sdist and wheel
make wheel-smoke    isolated installed-wheel help and demo
make demo           generate the committed example output locally
make docs-check     validate links/contracts/examples/assets
make security       dependency, static, and secret checks
make mutation       mutate critical pure logic
make benchmark      run the deterministic local performance scenario
make verify         all required non-mutation/non-benchmark completion checks
```

The exact underlying commands will be documented in `CONTRIBUTING.md` and must work without
hidden IDE configuration. CI invokes the same targets. Test failures emit concise logs,
JUnit/coverage XML, and safe generated artifacts where useful.

## CI and packaging

CI contains:

- fast quality: formatting, lint, typing, unit tests;
- full tests: unit, integration, black-box functional, branch coverage, 90% enforcement;
- package: sdist/wheel, isolated install, CLI help, demo, artifact validation;
- security/dependencies: audit, Bandit, secret scan;
- a declared Python-version matrix with dependency caching that cannot mask correctness.

Product tests never need the network. CI artifacts must not contain real traces or secrets.
Dependency updates are configured for package and workflow manifests.

## Documentation and open-source readiness

Deliver and cross-link:

- `README.md` as the tested product page, with actual demo graph/report imagery;
- `docs/architecture.md`, `docs/schema.md`, `docs/privacy.md`, `docs/testing.md`,
  `docs/cli.md`, and a release procedure;
- deterministic examples and OTLP fixture provenance;
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`;
- GitHub issue/feature templates, pull-request template, CI, and dependency updates.

Do not invent maintainers, organizations, contact emails, funding, adopters, download counts,
testimonials, integrations, production readiness, benchmarks, or badges without real backing.
Apache-2.0 remains the license. A NOTICE is added only if a real attribution requires it.

README must prominently state:

> JourneyGraph does not collect traces. It analyzes the traces and event exports you already
> have.

It distinguishes individual trace inspection from cross-trace graph analysis, gives a tested
five-minute quickstart and small real input/output examples, states format maturity honestly,
documents privacy/non-goals/limitations, and naturally explains AI agent analytics, LLM
observability, OpenTelemetry, graph analytics, trace analysis, journey analysis, agent
evaluation, and path mining. “OpenInference” appears only as a roadmap/semantic-convention
reference unless tested compatibility is implemented.

## Milestones

### M0 — Research, contracts, and harness

- Verify repository state, instructions, test reference, official OTLP contract, Python and
  dependency facts.
- Create this approved living plan.
- Add packaging, canonical commands, base documentation, and initial CI.
- Acceptance: package skeleton builds; commands are discoverable; no product claim exceeds
  evidence.

### M1 — Canonical ingestion and normalization

- Implement domain schema, JSONL/CSV/optional Parquet/OTLP readers, validation, normalization,
  duplicate/privacy/relationship policies, canonical export.
- Deliver user-visible functional validation scenarios alongside code.
- Acceptance: malformed/empty/privacy/order/duplicate cases behave exactly as contracted.

### M2 — Graph and analytics

- Implement nodes/transitions, exact paths, entries/terminals, retries/loops, failures,
  drop-offs, outcomes/cohorts, and metrics.
- Add independent fixture oracles, invariants, properties, and black-box analysis scenarios.
- Acceptance: all totals reconcile and input permutation/repeated runs are equivalent.

### M3 — Reports and demo

- Implement deterministic JSON, escaped static HTML/SVG, safe artifact publication, packaged
  synthetic dataset, and demo command.
- Acceptance: a fresh installed wheel produces inspected, valid, non-executable artifacts.

### M4 — Public documentation and repository readiness

- Complete README, architecture/schema/privacy/testing/CLI/release docs, community files,
  templates, CI, dependency configuration, and actual generated README asset.
- Acceptance: docs check and README quickstart pass; claims match tests.

### M5 — Final hardening and handoff

- Run formatting, lint, types, all test layers, 90% statement/branch coverage, build, isolated
  wheel smoke, demo, docs, security, mutation, benchmark, repeated full verification, and
  final secret/dead-code/scope review.
- Update outcomes/retrospective and make small Conventional Commit-style local commits.
- Acceptance: every definition-of-done check passes or an exact non-negotiable blocker is
  recorded; no push/merge/release occurs.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| OTLP JSON exporters differ in envelopes/encodings | Support and fixture only the verified protobuf JSON trace contract; label experimental; actionable unsupported-shape errors. |
| Privacy filtering creates a false anonymity impression | Key denylist plus allowlist, downstream leakage tests, prominent residual-sensitivity docs. |
| Ambiguous “loop” semantics | Publish the exact return-to-category definition and manually verified examples; keep retry separate. |
| Equal timestamps/parent disagreement change paths | Fixed timestamp/ID order; parent diagnostics rather than hidden reorder; metamorphic tests. |
| Optional Parquet makes installs heavy | Separate extra; JSONL demo and wheel smoke need no PyArrow; clear install error. |
| HTML/SVG labels execute markup | Contextual escaping, CSP, no JS/foreign objects, adversarial parser tests. |
| Coverage target encourages brittle tests | Behavior oracles/invariants first; simplify code; no gaming/exclusion. |
| Mutation tool incompatibility | Try documented tool and one focused alternative; record exact blocker without lowering tests. |
| Large reports become unreadable or memory-heavy | Deterministic top-N display with full machine data where documented; benchmark scaling; honest limits. |
| Scope expands into collection/prediction/integrations | Enforce non-goals; defer after acceptance, never add optional features merely to market v0.1. |

## Acceptance criteria / definition of done

- Fresh documented setup, build, and isolated wheel installation succeed.
- Installed `journeygraph --help`, `validate`, `analyze`, and `demo` work through real
  subprocesses.
- Demo generates canonical JSONL, deterministic analysis JSON, static HTML, and SVG.
- Independent oracles confirm paths, transitions, loops, retries, failures, drop-offs,
  outcomes, latency, tokens, and cost.
- Same input/config gives equivalent output; shuffled input gives equivalent analytics.
- Sensitive/unknown fields do not appear in normalized, JSON, HTML, or SVG artifacts.
- Unit, integration, functional, installed-wheel, privacy, and security tests pass.
- Combined statement and branch coverage is at least 90% and critical paths have explicit
  positive/negative tests.
- Formatting, lint, strict typing, package build, docs checks, CI command parity, and security
  checks pass.
- README quickstart is executed and its inspected image comes from the real demo.
- Mutation testing runs on critical logic or records an exact tooling blocker after meaningful
  alternatives.
- Full suite runs repeatedly without order dependence.
- Performance results are reported only if measured.
- Public compatibility, quality, privacy, and performance claims exactly match evidence.
- Final diff is reviewed for scope creep, dead code, secrets, copied service-specific rules,
  and unnecessary files.
- Plan progress, decisions, discoveries, outcome, limitations, branch, commits, and Git status
  are current.

## Progress

- [x] 2026-07-21: Read the owner request and all initial repository instructions/product
  documents.
- [x] 2026-07-21: Verified clean `main`, remote, baseline history, initial file inventory, and
  Apache-2.0 license.
- [x] 2026-07-21: Created `feat/journeygraph-mvp` as a linked worktree without modifying
  `main`.
- [x] 2026-07-21: Read and adapted the requested CyberBrain testing/coverage/commands/checklist
  principles while excluding service-specific rules.
- [x] 2026-07-21: Created this self-contained ExecPlan under the task's explicit implementation
  approval.
- [ ] Verify official OTLP, Python, packaging, dependency, and license facts; record sources.
- [ ] Complete M0 repository harness.
- [ ] Complete M1 ingestion and normalization.
- [ ] Complete M2 graph and analytics.
- [ ] Complete M3 reporting and demo.
- [ ] Complete M4 documentation/open-source readiness.
- [ ] Complete M5 hardening, commits, and handoff.

## Discoveries

- The initial repository is intentionally minimal and clean; there is no legacy product code
  or user work to migrate around.
- The environment's active repository root was an empty task workspace while the canonical
  checkout was read-only. A Git linked worktree safely reconciles the paths and keeps the
  requested branch in the canonical repository.
- The CyberBrain reference's black-box/AAA/coverage principles transfer well, but its HTTP,
  ClickHouse, settings, `.venv313`, package names, and prohibition on unit tests are specific
  to that service and are deliberately not copied.
- Current shell startup emits a harmless pyenv rehash warning because its shim directory is
  read-only. It is environment noise, not repository behavior.

## Decision log

- **2026-07-21 — Work in a linked Git worktree.** This preserves the clean default checkout,
  obeys the sandbox write boundary, and keeps branch/commit history attached to the canonical
  repository.
- **2026-07-21 — Owner approval is already satisfied.** The task explicitly says to create
  and execute the plan without separate approval, so implementation continues after the plan
  is committed/recorded.
- **2026-07-21 — Standard-library analytical core.** It minimizes runtime coupling and supply
  chain. Optional PyArrow is isolated to Parquet ingestion.
- **2026-07-21 — JSONL and CSV stable; Parquet optional; OTLP/JSON experimental.** This is the
  narrowest useful, honest format surface that covers canonical event data and one verified
  standards path.
- **2026-07-21 — Exact deterministic analytics, no clustering/prediction.** Exact paths and
  return loops are explainable and testable; leakage-safe prefix prediction remains roadmap.
- **2026-07-21 — Chronological ordering with ID tie-break.** Parent links diagnose quality but
  cannot silently contradict recorded time.
- **2026-07-21 — Exact duplicate removal, conflicting duplicate rejection.** This gives safe
  idempotence while surfacing disagreement.
- **2026-07-21 — Missing outcome becomes failure only for terminal error, otherwise dropoff.**
  This keeps retry-then-success correct and makes incomplete traces visible.
- **2026-07-21 — Fixed artifact names and no JavaScript.** This narrows path/injection risks
  while preserving a useful offline report.

## Outcomes and retrospective

Not yet complete. At the end, record shipped behavior, measured quality/coverage/performance,
commands actually run, local commits, remaining limitations, roadmap, and anything that
should change in a later plan. Do not declare the MVP complete while a required check fails.
