# Changelog

All notable user-visible changes to JourneyGraph will be documented in this file.

The project intends to follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). During the alpha period, breaking
changes may occur in minor versions, but they must be called out with migration guidance.

## Unreleased

### Added

- Added a privacy-safe real-trace discovery protocol, strict metadata-only evidence schema,
  synthetic failed/successful run example, publication gate, and repository checks that reject
  private evidence examples or tracked files under `data/private/`.
- Prepared a secretless PyPI Trusted Publishing workflow that builds once, verifies exact
  distributions, publishes only through a protected OIDC job, and checks remote hashes plus a
  fresh install after an authorized future release.
- Added strict distribution identity/content checks, a deterministic SHA-256 release manifest,
  package metadata links for the changelog and security policy, and focused unit coverage.

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

Version headings and release dates will be added only after an authorized release actually
exists.
