## Outcome

Describe the user-visible problem and the completed outcome. Keep the scope narrow.

## Planning and scope

- Related issue:
- Approved ExecPlan, when required:
- Deliberate non-goals:
- Unrelated changes intentionally excluded:

## Contract changes

Describe any change to:

- canonical fields, validation, ordering, duplicates, or outcomes;
- node/path identity, graph weights, paths, retries, loops, cohorts, or metrics;
- CLI syntax, exit codes, Python API, artifacts, or schemas;
- format maturity or compatibility boundary;
- documentation or migration requirements.

Write “None” when there is no public contract change.

## Privacy and security

- Data newly read, retained, emitted, transmitted, or written:
- Metadata allowlist/denylist impact:
- HTML/SVG/filesystem/dependency impact:
- Residual risk and limitations:
- Fixture/data classification (`synthetic`, `no fixture`, or separately approved
  `real-derived`):
- For `real-derived` only: opaque public-use permission reference plus independent reviewer role
  and review date (never paste the permission text or partner identity):

Confirm that no raw or merely pseudonymized trace, prompt, response, identifier, partner detail,
private dimension, secret, local path, or unreviewed generated artifact is included. Key-based
filtering and the phrase “fully sanitized” are not substitutes for explicit public-use permission
and independent disclosure review.

## Verification

List the exact commands run and their results. Typical completion evidence includes:

```text
make format-check
make lint
make typecheck
make coverage
make wheel-smoke
make docs-check
make security
```

When applicable, also report `make mutation`, `make benchmark`, repeated full-suite runs, and
manual artifact inspection. Do not mark an unchecked command as passed.

## Documentation and claims

- [ ] Relevant architecture, schema, privacy, CLI, testing, and release docs are updated.
- [ ] When applicable, `CHANGELOG.md` records the user-visible change under `Unreleased`;
      otherwise the PR explains why it is not applicable.
- [ ] Compatibility, quality, privacy, security, and performance claims match evidence.
- [ ] Primary sources are linked for unstable standards or dependency facts.
- [ ] No badge, benchmark, integration, adopter, maintainer, or production-readiness claim was invented.

## Final review

- [ ] When applicable, new behavior has independent positive and negative tests; otherwise
      the PR explains why it is not applicable.
- [ ] Tests were not weakened and required behavior was not removed to pass checks.
- [ ] The analytical core remains local-first, vendor-neutral, deterministic, and explainable.
- [ ] Provider-specific logic remains isolated in its importer.
- [ ] The diff contains no secret, private trace, prompt, response, personal data, local path, or unrelated generated file.
- [ ] Every fixture is synthetic, or its exact real-derived public use has written permission,
      aggressive minimization, and a recorded independent disclosure review.
- [ ] When an ExecPlan is required, its material assumptions, decisions, discoveries,
      progress, and outcomes are current; otherwise the PR records that it is not applicable.
- [ ] I did not change project remote settings, create a tag/release, or publish an artifact; merge and publication remain maintainer-controlled.
