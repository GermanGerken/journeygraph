# Privacy-Safe Real-Trace Discovery ExecPlan

This living plan covers the repository-side preparation for
[#5](https://github.com/GermanGerken/journeygraph/issues/5). It establishes a consistent intake,
evidence, and publication-review protocol before any `v0.2` compatibility scope is chosen.

It does not claim that a partner has been recruited, authorize receipt of data through an
unspecified channel, grant a data license, or permit a real trace or derived artifact to be
committed or attached publicly.

## Purpose and observable outcome

JourneyGraph needs real-export evidence to choose one early user/job and the first narrow
compatibility slice. That evidence must be comparable across successful and failed imports and
must not weaken the local-first privacy boundary.

The repository outcome of this plan is:

- a public protocol with intake, provenance, permission, retention, storage, sanitization,
  analysis, gap-priority, and publication gates;
- a strict JSON Schema for metadata-only evidence bundles;
- a valid synthetic example showing a failure and separate successful retry;
- automated schema, reference-integrity, record-class, and private-path checks;
- stronger contribution and pull-request language for real-derived material;
- explicit owner-only work required to run the actual study.

## Scope and authorization

The repository owner asked to take the next logical step after Stage 0 and accepted parallel
work on issues #4 and #5. This plan scopes issue #5 to a separate local feature branch,
repository documentation and checks, tests through the standard gates, a pushed feature branch,
and a draft pull request.

The following require new facts or owner coordination and are not performed by this plan:

- choosing or configuring a private intake channel or storage system;
- contacting or recruiting design partners;
- accepting, copying, opening, or transforming any real export;
- creating partner agreements or deciding their legal sufficiency;
- publishing a real-derived summary, fixture, screenshot, log, or issue;
- choosing `v0.2` producer/exporter versions without completed evidence.

The PyPI Trusted Publishing work for #4 remains in an independent branch because release OIDC
security and trace disclosure review have different reviewers and failure modes.

## Verified starting state

Verified on 2026-07-21:

- Issue #5 requires 2–3 privacy-reviewed exports from at least two source families and retains
  separate acceptance criteria for provenance, failures, gap categories, and exact versions.
- `data/private/` is ignored, but no repository check proves that a previously tracked private
  path is absent.
- Fixtures are synthetic and contribution guidance already prohibits raw traces and secrets.
- JourneyGraph metadata filtering is key-based. IDs, labels, timestamps, rare paths, allowed
  values, and `normalized.jsonl` can remain identifying.
- The repository has no real-trace evidence schema, standard record, intake channel, partner
  evidence, or independently approved public summary.

## Working product hypotheses

The initial persona hypothesis is an AI or agent engineer who owns an agent workflow and can
export traces locally.

The target job hypothesis is: given a privacy-reviewed batch export, identify recurring retries,
loops, failures, or drop-offs and choose one concrete debugging target without uploading traces.

These are deliberately hypotheses. Their evidence links remain empty in the synthetic example.
Only actual privacy-reviewed partner runs can partially validate, validate, or reject them.

## Evidence design

`docs/research/schemas/real-trace-evidence-v1.schema.json` defines three record classes:

- `synthetic_example`: public teaching material whose IDs use the `example-` prefix;
- `private_evidence`: exact private dimensions and approved encrypted storage;
- `public_summary`: bucketed dimensions and a mandatory passed permission/disclosure review.

Every bundle records the study hypotheses, datasets, runs, gaps, and publication decision.
Dataset records require producer/version provenance, permission basis and allowed-use matrix,
retention/deletion state, access roles, input dimensions, and sanitization reviews. Run records
use structured commands without local paths and require result/exit code, timings, warnings,
failures, transformations, dropped fields, intervention, artifact review, mapping gaps, and
actionability.

The schema rejects extra properties and constrains text and IDs to reduce accidental leakage. It
cannot prove that free text is safe, that permission is valid, or that aliases are anonymous;
manual review remains mandatory.

## Repository validation

`scripts/check_docs.py` will:

1. validate the research schema itself with Draft 2020-12;
2. validate the committed synthetic example with date/URI format checks;
3. require committed examples to be `synthetic_example` or passed `public_summary`, never
   `private_evidence`;
4. verify unique dataset/run/gap IDs, same-dataset supersession, and bidirectional run/gap
   references;
5. require every synthetic ID and alias to begin with `example-`;
6. reject path separators in evidence strings (except the canonical public issue URL), covering
   absolute, relative, repository-private, Windows, and UNC references; also reject any nested,
   symbolic-link, or non-JSON entry in the public examples directory;
7. fail when `git ls-files` reports anything under `data/private/`;
8. keep the protocol, schema, example, and this ExecPlan in the durable required-file set.

These checks are guardrails. They do not scan ignored private content and do not replace the
dataset-level automated and manual reviews.

## Privacy and failure handling

The protocol requires data-owner minimization before transfer, a second review before
JourneyGraph, consistent ID transformation, timestamp protection, label/rare-path review, and
post-run inspection of every artifact. Permission for private analysis, derived findings,
public aggregates, and public fixtures is recorded separately.

Failed imports are immutable evidence entries. A corrected run may reference the prior run but
must not overwrite it. If generated output contains unsafe material, artifact review fails and
the material remains private while sanitization is repeated.

## Acceptance criteria for this repository preparation

- [x] Persona and target job are documented explicitly as unvalidated hypotheses.
- [x] Intake, provenance, retention, access, sanitization, run, gap, and publication gates are
  documented.
- [x] Evidence JSON Schema is strict and validates the public synthetic example.
- [x] Synthetic example preserves a failed attempt and a separate successful retry.
- [x] Public summaries require permission, bucketed dimensions, and independent review.
- [x] Documentation checks reject invalid references, private evidence examples, and tracked
  `data/private/` files.
- [x] README, privacy guidance, contribution guidance, PR template, changelog, and plan index are
  consistent with the protocol.
- [x] Local checks pass, including the full test matrix, coverage, wheel smoke, documentation,
  static analysis, dependency audit, and secret scan.
- [x] Clean GitHub CI passes for the draft PR after synchronization with the current `main`.
- [x] No partner, real export, private service setting, or compatibility claim is invented.

## Issue #5 acceptance status

Repository preparation cannot close #5:

- [x] A primary persona and single target job are documented, currently as hypotheses.
- [ ] 2–3 legally usable exports from at least two source families have been exercised.
- [ ] Every real dataset has completed provenance, permission, retention, and sanitization.
- [x] Public policy prohibits raw sensitive traces and gates any real-derived fixture.
- [x] One schema records successful and failed runs consistently.
- [x] The gap schema distinguishes ingestion, canonical-model, analysis, and documentation gaps.
- [ ] Exact first-slice producer/exporter versions have been chosen from evidence.

The checked repository items describe the mechanism, not real-world validation.

## Progress

- [x] 2026-07-21: Reviewed issue #5, repository privacy controls, fixtures, ignore rules, and
  current documentation checks.
- [x] 2026-07-21: Chose a separate branch and draft PR from `origin/main`.
- [x] Implement the protocol, schema, synthetic example, repository checks, and documentation
  integration.
- [x] Run local gates and independent diff review; all actionable findings were addressed.
- [x] Pushed `feature/real-trace-discovery` and opened draft
  [PR #12](https://github.com/GermanGerken/journeygraph/pull/12), advancing issue #5 without
  closing it.
- [x] Verified clean GitHub CI for implementation commit
  `33af164e193b137f9baf1fce68b08b5c46395a0f` in
  [run 29854308692](https://github.com/GermanGerken/journeygraph/actions/runs/29854308692):
  security, fast quality, package/wheel, GitGuardian, and full tests on Python 3.11–3.14 passed.
- [x] Synchronized with `main` after PR #11 merged as `7d4296b`, preserving both release and
  real-trace documentation checks; the combined local `make verify && make test` passed with
  158 tests, 93.05% branch-aware coverage, and separate 100-unit/22-integration/36-functional
  reruns.
- [x] Verified clean GitHub CI for synchronized commit
  `84b087efe2df7ca66f2b6536a4f7ee62af9c9294` in
  [run 29855243634](https://github.com/GermanGerken/journeygraph/actions/runs/29855243634):
  security, fast quality, package/wheel, GitGuardian, and full tests on Python 3.11–3.14 passed.

## Decision log

- **Hypotheses, not invented validation.** A plausible persona/job gives the study a focus while
  zero real runs remain clearly visible.
- **Metadata-only evidence.** The schema records safe operational facts and opaque references;
  it must never become a second trace format.
- **Exact private, bucketed public.** Exact dimensions are useful for private reproducibility but
  can identify a partner when published.
- **Permission is use-specific.** Private analysis does not imply permission for aggregates or a
  fixture.
- **Preserve failures.** Failed imports and intervention costs are product evidence, not noise to
  be replaced by a successful retry.
- **Independent publication review.** Key-based filtering and aliases cannot prove anonymity.
- **No external intake yet.** Channel, storage, access roles, retention ownership, and reviewer
  must be established before recruitment.

## Outcomes and next owner actions

Repository preparation is implemented. After synchronization with the merged Trusted Publishing
work, local evidence on 2026-07-21 includes 158 passing tests with 93.05% branch-aware coverage,
separate 100-unit/22-integration/36-functional reruns, clean format/lint/mypy/docs/security gates,
a passing wheel smoke test, and an independent final review with no findings. The implementation
is published for review in draft PR #12; its pre-synchronization repository CI matrix passed in
run 29854308692, and the synchronized repository CI matrix passed in run 29855243634.

After merge, the owner must establish the private operating setup, recruit 2–3 design partners
through the provenance gate, and populate private evidence records. Issue #5 and any `v0.2`
compatibility decision remain open until those records meet the issue thresholds.
