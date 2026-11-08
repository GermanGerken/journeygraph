# Changelog

All notable user-visible changes to JourneyGraph will be documented in this file.

The project intends to follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). During the alpha period, breaking
changes may occur in minor versions, but they must be called out with migration guidance.

## Unreleased

### Added

- Added experimental `--format otlp-proto` (one binary OTLP/HTTP `ExportTraceServiceRequest`)
  and `--format otlp-proto-file` (OpenTelemetry Collector file exporter `format: proto`,
  uncompressed and length-prefixed), decoded by a standard-library protobuf wire decoder
  with the existing OTLP mapping; no runtime dependency is added.
- Added the experimental `--preset langsmith-runs` for LangSmith run objects from
  `runs.query` / `POST /api/v2/runs/query`, and `[N]`/`[-1]` array indexes in mapping paths.
- Added experimental `--preset langfuse-observations` and `--preset phoenix-spans` on
  `validate`, `analyze`, `diff`, and `check`: packaged field mappings for the documented
  Langfuse enriched observations export and Arize Phoenix REST span objects, plus
  `journeygraph presets [--show NAME]`. They follow vendor documentation checked on
  2026-11-08 and were not tested against real exports.
- Added the `utc_naive` timestamp unit to field mappings for `YYYY-MM-DD HH:MM:SS[.fraction]`
  values without an offset, read as UTC.
- Added `journeygraph inspect INPUT [--sample N] [--mapping-out PATH] [--show-values]`,
  which profiles a JSON Lines, CSV, or Parquet sample by path, type, and shape without
  printing values and writes a commented draft field mapping; required fields it cannot fill
  stay as `TODO` lines. `--show-values` opts in to short status, outcome, and operation-type
  tokens for drafting value maps.
- Added experimental `--mapping FILE` on `validate`, `analyze`, `diff`, and `check`: a
  declarative TOML field mapping converts JSON Lines, CSV, or Parquet records of any shape into
  canonical events before validation, with dotted source paths, constants, value maps, epoch
  timestamp units, and durations from a field or an end-minus-start pair. Unmapped source
  fields are ignored and counted in an `unmapped_source_fields_ignored` warning; metadata
  privacy rules apply unchanged. The Python API gains `mapping=` and `load_mapping`.

## [0.2.0] - 2026-11-08

### Added

- Added the experimental `--format otlp-jsonl` input for OpenTelemetry Collector file-exporter
  output (one `ExportTraceServiceRequest` per line), decoded with the existing OTLP mapping.
- Added `journeygraph diff BASELINE CANDIDATE`, which writes `diff.json` and `diff.html` with
  outcome, category, transition, path-variant, and metric differences, a Newcombe interval for
  the change in success, and up to 15 ranked notable changes.
- Added `journeygraph check INPUT --rules RULES.toml [--baseline ...] [--summary-md ...]`
  with threshold and regression rules; it exits with the new code `5` when a rule fails.
- Added `compare_files`, `write_comparison`, and `Comparison` to the Python API.
- Added path variants (`path_variants`) that group traces after collapsing consecutive repeated
  blocks of up to four categories, recurring two- and three-step sequences
  (`sequence_patterns`), and a `sequence_association` finding, with Path variants and Recurring
  sequences sections in the HTML report.
- Added `journeygraph analyze --outcome`, `--since`, and `--until` trace filters; the payload
  records them under `filters`, and `normalized.jsonl` contains only retained traces.
- Added ranked, reproducible key findings to `analysis.json` (`findings`) and to the top of
  `report.html`: outcome associations, error hotspots, duration and cost concentration, and
  retry prevalence, each with support, a baseline, a Wilson interval where applicable, and an
  association-only statement. `journeygraph analyze --min-support N` (default 3) controls
  eligibility.
- Added per-category error counts, duration/token/cost summaries, and visiting-trace outcomes
  to `nodes`, and containing-trace outcomes to `transitions`.
- Replaced the elliptical SVG layout with a deterministic layered left-to-right layout that
  routes long transitions around categories, colors categories by error-event rate and
  transitions by success among known outcomes, dashes return transitions, and includes a text
  legend. At most 60 categories are drawn.
- Added an "Operation categories" table to the HTML report.
- Added a pinned local OpenTelemetry Collector test-data harness, actual offline OpenInference
  and official OpenTelemetry Demo fixtures, per-file provenance, deterministic sanitization,
  disclosure checks, and semantic integration coverage. These samples are instrumented-demo
  evidence, not production traces or broad producer compatibility claims.
- Added strict provenance and upstream-pin schemas, one authoritative dependency/image manifest,
  an independently covered corpus checker, and installed-CLI acceptance of the instrumented
  OpenInference fixture.

### Changed

- The analysis schema version is now `1.2`. All 1.0 keys, identities, and orderings are
  unchanged. Nodes, transitions, and the top level gained required fields (`findings`,
  `path_variants`, `sequence_patterns`, `filters`); finding items carry `pattern_id` and
  `labels`, and `node_id` is `null` for sequence findings. Strict validators pinned to the 1.0
  schema must update; readers that ignore unknown fields need no change.

### Fixed

- Corrected the README demo outcome counts, which still described the pre-0.1.2 inference.

Migration: strict validators pinned to analysis schema `1.0` must accept schema `1.2`; readers
that ignore unknown fields need no change. CI scripts that treat every non-zero exit as an
input error should note that `journeygraph check` uses the new exit code `5` for failed rules.

## [0.1.2] - 2026-08-02

### Changed

- Classify traces without an explicit business outcome as `unknown` regardless of terminal
  event or span status; technical error events remain visible without inventing business
  failure or drop-off.
- Emit an `otlp_chronological_adjacency` warning for accepted OTLP datasets and label report
  paths, transitions, repetitions, returns, and error signals with neutral chronological terms.

Migration: workflows that relied on an omitted outcome becoming `failure` or `dropoff` must now
set that business outcome explicitly; otherwise the trace is reported as `unknown`.

## [0.1.1] - 2026-07-22

### Added

- Added native Windows Python 3.12 distribution and installed-CLI verification covering the
  exact wheel, CRLF and Unicode input, native paths, deterministic reports, and the packaged
  demo.
- Added a privacy-safe real-trace discovery protocol, strict metadata-only evidence schema,
  synthetic failed/successful run example, publication gate, and repository checks that reject
  private evidence examples or tracked files under `data/private/`.
- Prepared a secretless PyPI Trusted Publishing workflow that builds once, verifies exact
  distributions, publishes only through a protected OIDC job, and checks remote hashes plus a
  fresh install after an authorized future release.
- Added strict distribution identity/content checks, a deterministic SHA-256 release manifest,
  package metadata links for the changelog and security policy, and focused unit coverage.

### Fixed

- Excluded ambiguous allowlisted metadata fields when multiple source spellings normalize to the
  same output key, with a privacy-safe warning instead of silent last-value replacement.
- Mapped malformed CSV parser failures to the documented validation exit code and an actionable,
  sanitized format error.
- Preserved the resolved source path in Python API analyses so later working-directory changes
  cannot bypass input/artifact collision protection.

### Security

- Limited the publication credential surface to one environment-protected job with only
  `id-token: write`, no long-lived package token, and full commit-SHA pins for external actions.

## [0.1.0] - 2026-07-21

### Added

- Canonical `journeygraph.event/v1` event schema and immutable domain contracts.
- Local JSON Lines and CSV readers plus optional Parquet decoding.
- Experimental import of one uncompressed OTLP/HTTP JSON `ExportTraceServiceRequest` shape.
- Deterministic UTC ordering, duplicate handling, parent diagnostics, and outcome reconciliation.
- Metadata allowlisting with a permanent sensitive-key denylist and structured safe warnings.
- Stable SHA-256 aggregate node and exact-path identities.
- Weighted transitions, exact paths, entries, terminals, retries, return loops, failure points,
  drop-off points, outcomes, cohorts, and event-level duration/token/cost summaries.
- Local `validate`, `analyze`, and `demo` commands.
- Deterministic JSON and normalized JSONL, escaped static HTML, and standalone SVG reports.
- Guarded local artifact publication with overwrite, traversal, direct symlink-root, and input
  collision checks.
- Deterministic synthetic AI-agent demo data.
- Unit and black-box functional tests, strict typing, linting, branch coverage enforcement,
  package smoke checks, documentation checks, security tooling, mutation configuration, and a
  deterministic local benchmark harness.
- Architecture, schema, privacy, CLI, testing, contributing, conduct, security, changelog, and
  release documentation.

### Security

- Added contextual HTML/XML escaping, a restrictive static-report Content Security Policy, and
  adversarial injection coverage.
- Hardened case-insensitive input/artifact collision checks, UTF-8 and XML-safe Unicode
  handling, finite JSON serialization, and safe ordinal diagnostics that never echo rejected
  metadata keys.
- Preserved exact timezone-aware Parquet timestamps from seconds through nanoseconds, including
  pre-epoch values, while mapping schema and row-conversion failures to actionable format errors.
- Expanded the non-overridable metadata denylist for common account, customer, employee, user,
  and visitor identifier key names; arbitrary allowlisted values remain explicitly non-anonymous.
- Added dependency audit, static analysis, and tracked-file secret scanning to the repository
  quality interface.

### Known limitations

- OTLP/JSON import is experimental and supports only the documented protobuf JSON request shape
  and selected field mappings.
- Parquet requires the optional PyArrow dependency.
- Metadata filtering is key-based and does not anonymize allowlisted values, labels, identifiers,
  timestamps, or aggregates.
- Multi-file publication is not transactional, and hostile-input resource-exhaustion resistance
  is not claimed.
- JourneyGraph does not collect traces and does not provide hosted operation, real-time streaming,
  prediction, clustering, causal attribution, an LLM judge, or prompt optimization.

Version headings and release dates are added only for authorized release candidates and must
match the final published release.

[Unreleased]: https://github.com/GermanGerken/journeygraph/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/GermanGerken/journeygraph/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/GermanGerken/journeygraph/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/GermanGerken/journeygraph/releases/tag/v0.1.0
