# Semantic Safety Patch ExecPlan

This living plan implements Stage 0 of the post-audit roadmap. It is intentionally limited to
correcting unsafe analytical defaults and making the current OTLP execution-model boundary
visible. It does not implement parent-aware analysis, claim compatibility with a producer, or
replace the real-trace evidence required by issue #5.

## Purpose and observable outcome

Before this patch, JourneyGraph 0.1 turned a missing explicit outcome into `failure` when the
terminal status was `error` and into `dropoff` otherwise. It also built paths and transitions from
timestamp-sorted spans while parent relationships remain diagnostic. Both behaviors can make
the report stronger than the source evidence supports.

After this patch:

- the latest explicit outcome still wins;
- every trace without an explicit business outcome is `unknown`;
- `status: error` remains a technical error event but does not invent business failure;
- accepted OTLP datasets emit a durable warning that paths and transitions are chronological
  adjacency, not parent-aware control flow;
- the HTML report uses neutral chronological language and displays the `unknown` outcome count;
- explicit `failure`, `dropoff`, and `handoff` behavior remains available and tested;
- the public analysis schema and JSON keys remain compatible.

## Scope and non-goals

In scope are normalization, warnings, static report labels, regression coverage, public
documentation, and release notes. The implementation may retain historical outcome-source
enum values in the v1 analysis schema so previously generated payloads remain describable.

Out of scope are parent-child graph construction, root-to-leaf variants, concurrency modeling,
session grouping, source-specific outcome inference, new importers, UI/server work, streaming,
prediction, and a package release. A version bump, tag, publication, and remote ruleset change
require their normal release or repository-administration authorization.

## Contract decisions

### Business outcome

An event status and a journey outcome answer different questions. `status: error` describes a
technical event. `outcome: failure` describes an explicit business result. Missing business
evidence therefore maps to `unknown`, not to a guessed result.

The existing outcome vocabulary and analysis schema version remain unchanged. This is a safety
correction within the early-alpha contract, documented prominently in the changelog.

### Execution model

Canonical events remain deterministically sorted by timestamp and then `step_id`. Aggregate
edges, paths, adjacent repetitions, and return sequences continue to use that order. For OTLP,
the tool must call this chronological adjacency and warn that siblings or concurrent spans can
appear adjacent without representing sequential control flow.

Parent-aware analysis will be designed separately from privacy-reviewed real hierarchical
traces. This patch does not guess that model.

## Test strategy

- Unit regression: terminal `ok`, `error`, and `unset` without an explicit outcome all become
  `unknown` with source `missing`.
- Functional regression: the installed CLI analyzes missing-outcome success-like and error-like
  traces as unknown, retains the technical error point, and produces no drop-off point.
- Integration regression: accepted OTLP input includes the chronological-adjacency warning.
- Reporting regression: the static report displays Unknown and neutral chronological labels.
- Existing explicit failure, drop-off, handoff, retry-then-success, schema, determinism, privacy,
  and package tests continue to pass.

## Acceptance criteria

- [x] Missing explicit outcomes never produce `failure` or `dropoff` in normalization.
- [x] Terminal technical errors remain visible in `failure_points` with no terminal business
  failure count unless the outcome is explicitly `failure`.
- [x] OTLP validation and analysis emit `otlp_chronological_adjacency`.
- [x] HTML and public docs distinguish chronological adjacency from parent-aware control flow.
- [x] Explicit drop-off coverage no longer depends on an inferred missing outcome.
- [x] Targeted tests and the canonical `make verify` gate pass.
- [x] The final diff contains no parent-aware implementation or unrelated feature work.

## Progress

- [x] 2026-08-01: Re-read the product brief, current contracts, active discovery plan, and audit
  findings on `origin/main` at `f2207ce`.
- [x] Added failing unit, integration, functional, and reporting regressions before production
  changes; seven tests failed on the old semantics as expected.
- [x] Implement production behavior and documentation.
- [x] Run targeted and canonical verification.
- [x] Review the final diff and record outcomes.

## Decision log

- **Missing means unknown.** No default inference policy is allowed without source-specific
  evidence and an explicit future contract.
- **Errors remain event-level.** Removing business-outcome inference must not hide technical
  failures from the existing error-point analysis.
- **Warn instead of pretending hierarchy.** The current deterministic chronological model stays
  intact until real hierarchical traces justify a separate execution model.
- **Keep v1 keys stable.** Neutral language changes presentation and documentation without
  renaming machine-readable `paths`, `transitions`, `retries`, `loops`, or `failure_points`.

## Outcomes and retrospective

The patch changes one production inference point, adds one dataset-level OTLP warning, and
updates static report language without changing machine-readable keys or schema versions. The
explicit drop-off fixture now supplies its business outcome. New black-box coverage proves that
an error event without a business outcome remains visible while the trace outcome is unknown.

Verification on macOS with Python 3.12 completed on 2026-08-01: 59 targeted tests passed; the
canonical `make verify` gate passed with 169 tests and 93.05% combined branch-aware coverage,
plus Ruff, mypy, wheel smoke, documentation, dependency audit, Bandit, and secret scanning.
Native Windows evidence remains the responsibility of GitHub CI when a pull request is opened.
