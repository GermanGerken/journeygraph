# PyPI Trusted Publishing Preparation ExecPlan

This living plan covers issue
[#4](https://github.com/GermanGerken/journeygraph/issues/4). It first prepared a reviewable,
secretless publication path without authorizing external changes, then records the separately
authorized `v0.1.1` release and its public verification.

## Purpose and observable outcome

The authorized `v0.1.1` release built JourneyGraph once, verified the exact wheel and source
distribution, published those same bytes through PyPI Trusted Publishing, and independently
verified the published hashes and fresh-install journey.

The repository outcome of this plan is:

- a dedicated release workflow with the smallest practical OIDC permission surface;
- executable checks for tag/version identity, archive contents, metadata, and SHA-256 hashes;
- a post-publication check against PyPI followed by an isolated install and demo;
- documentation of the owner-only controls required before the workflow can publish.

The verified package is available from
[PyPI](https://pypi.org/project/journeygraph/0.1.1/). The README installation may now use
`python -m pip install journeygraph`.

## Authorization and scope

The repository owner asked to begin the next logical step after Stage 0 and accepted work on
issues #4 and #5. This plan scopes issue #4 to a local feature branch, repository edits,
tests, a pushed feature branch, and a draft pull request for review. The following remain
separate owner checkpoints requiring exact authorization:

- creating or changing the GitHub `pypi` environment or tag rules;
- registering a pending/existing publisher on PyPI;
- choosing and committing a release version;
- creating or publishing a tag or GitHub Release;
- approving the protected publish job;
- uploading, yanking, or otherwise changing a PyPI release.

Issue #5 is deliberately implemented in a separate branch and pull request because trace
privacy review and OIDC release security have different reviewers, evidence, and failure
modes.

## Verified starting state

Verified on 2026-07-21:

- `origin/main` is `da6b8c34bed88d0859f6a4f062f1f91158510258` and is protected by an
  active PR/required-CI ruleset.
- GitHub Release `v0.1.0` already exists. A future `release.published` workflow cannot run
  retroactively for that event.
- `https://pypi.org/pypi/journeygraph/json` returns `404`; this is a point-in-time check, not
  a name reservation.
- The repository has no GitHub environments and no package-registry workflow.
- `pyproject.toml` identifies version `0.1.0`; it is not changed by this preparation work.
- The existing package job builds and smoke-tests a wheel, but `make wheel-smoke` rebuilds.
  A release pipeline must instead build once and call `scripts/verify_wheel.py` directly on
  the final candidate.
- The local filesystem has only about 119 MiB available. Existing environments are preserved;
  full clean rebuild evidence must come from GitHub CI unless space is safely reclaimed.

## Primary sources

- [PyPA GitHub Actions publishing guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
- [PyPI Trusted Publishing security model](https://docs.pypi.org/trusted-publishers/security-model/)
- [GitHub secure use of third-party actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions)

The design follows the PyPI recommendation to isolate publishing in a dedicated workflow,
grant `id-token: write` only to the publishing job, retrieve distributions from a separate
build job, and protect publication with a GitHub environment. Every external action in the
release workflow is pinned to a full verified commit SHA.

## Workflow design

`.github/workflows/release.yml` responds only to `release.published`. It has no push, pull
request, `pull_request_target`, or permanent manual-dispatch trigger.

### Build and verify job

The build job has `contents: read`, checks out the release event's immutable `github.sha`
without persisted Git credentials, fetches history, and requires that commit to be an ancestor
of `main`. The tag name is used only for the independent tag/version identity check.
It then:

1. installs the declared development toolchain;
2. runs format, lint, strict typing, coverage, documentation, and security gates;
3. runs the complete tests a second time as required by the release procedure;
4. builds one wheel and one source distribution exactly once;
5. runs strict Twine metadata checks;
6. verifies tag/version agreement, archive safety, required contents, and embedded metadata;
7. smoke-tests the exact built wheel without rebuilding;
8. writes a SHA-256 manifest outside `dist/`;
9. uploads the two candidates and release evidence as separate short-lived artifacts.

### Publish job

The publish job waits for the build job, uses the protected `pypi` environment, and has only
`id-token: write`. Its two steps download the exact candidate artifact and invoke the pinned
PyPA publishing action. Metadata verification and attestations stay enabled. Existing files
are never silently skipped.

No checkout, build, test, arbitrary shell command, API token, password, or repository secret
is present in this job.

### Published-package verification job

After upload, a non-OIDC job downloads the build manifest, compares PyPI's version-specific
JSON file names and SHA-256 digests, downloads the selected wheel from the exact official file
URL, hashes those bytes again, and installs that local verified wheel into a new environment.
It then confirms the import resolves from `site-packages`, runs CLI help, and generates the
documented five-file demo. The bounded retry exists only for index propagation. A failure after
upload stops the workflow and requires an explicit corrective decision; it never overwrites a
release.

## Owner-only activation checkpoint

Before an authorized release, the owner must independently confirm:

1. the PyPI account email, at least two 2FA methods, and recovery codes;
2. a PyPI pending/existing publisher with project `journeygraph`, owner `GermanGerken`,
   repository `journeygraph`, workflow `release.yml`, and environment `pypi`;
3. a GitHub environment named `pypi` with manual approval and deployment tags restricted to
   `v*`; no secrets are needed;
4. a viable solo-maintainer approval policy (do not enable prevent-self-review without a
   second approver);
5. a reviewed release PR that updates `pyproject.toml`, `src/journeygraph/version.py`, and the
   changelog together;
6. green CI and local release prerequisites for the exact commit;
7. separate authorization for the exact tag, GitHub Release, and PyPI destination.

The owner should also protect release tags from mutation or deletion. The workflow binds each
run to the release event's recorded commit even if the tag is later moved, but immutable release
tags remain an important provenance and recovery control.

Because `v0.1.0` predates this workflow, the clean path is a new corrective release rather
than rebuilding or silently replacing existing release assets. The exact next version is a
release decision, not part of this preparation PR.

## Test and review strategy

- Unit tests create minimal synthetic wheel/sdist archives and independently verify positive,
  unexpected-file, unsafe-member, manifest, and changed-PyPI-hash paths.
- `scripts/check_docs.py` treats the workflow, plan, Changelog/Security metadata URLs, immutable
  action pins, single OIDC grant, and prohibited triggers/passwords as durable contracts.
- Focused local checks use the existing `.venv` because rebuilding it is unsafe on the nearly
  full disk.
- The draft PR's GitHub CI is the clean-environment completion gate for all supported Python
  versions, exact package build, coverage, documentation, and security checks.
- Review must inspect the workflow manually even when CI is green; a Trusted Publisher must be
  treated like a publishing credential.

## Acceptance criteria

- [x] Release workflow has no secret or long-lived credential input.
- [x] Only one job has `id-token: write`, and that job has only download and publish steps.
- [x] Every external release action is pinned to a full commit SHA.
- [x] Tag and package versions must match, and the tagged commit must belong to `main`.
- [x] Exactly one wheel and one sdist are built, inspected, hashed, and handed to publishing.
- [x] The exact wheel is installed and exercised before publication.
- [x] PyPI filenames/hashes and the clean-install demo are verified after publication.
- [x] Changelog and security project URLs are included in future package metadata.
- [x] Release documentation states the inactive prerequisites and owner checkpoints.
- [x] Repository CI is green for the draft PR.
- [x] The preparation PR created no tag, release, PyPI project, environment, or upload; every
  later external change was separately authorized and recorded.

## Progress

- [x] 2026-07-21: Verified repository, release, PyPI public-name, GitHub environment, and disk
  state.
- [x] 2026-07-21: Reviewed current PyPI, PyPA, and GitHub primary security guidance.
- [x] 2026-07-21: Chose a separate issue #4 branch and draft PR.
- [x] 2026-07-21: Implemented the release workflow, verification scripts, tests, metadata,
  documentation, and source/script static-security coverage.
- [x] 2026-07-21: Locally passed Ruff, strict mypy, documentation checks, 141 tests with
  93.05% statement/branch coverage, a second full three-layer test run, dependency audit,
  Bandit, secret scanning, strict Twine checks, exact distribution verification, and isolated
  wheel smoke.
- [x] 2026-07-21: Pushed `feature/pypi-trusted-publishing` at `e34c6b3` and opened
  [draft PR #11](https://github.com/GermanGerken/journeygraph/pull/11), linked as advancing
  issue #4 without closing it.
- [x] Verified clean-environment GitHub CI for commit
  `52614b520747eb2c1f609167dc80a18e326d076f` in
  [run 29851988460](https://github.com/GermanGerken/journeygraph/actions/runs/29851988460):
  security, fast quality, package/wheel, GitGuardian, and full tests on Python 3.11–3.14 passed.
- [x] 2026-07-22: Reverified that the public PyPI JSON endpoint still returns `404`, the
  protected GitHub `pypi` environment requires owner approval and permits only `v*` tags,
  and no open pull request conflicts with a corrective release candidate.
- [x] 2026-07-22: Selected `0.1.1` as the first PyPI release candidate because the existing
  GitHub `v0.1.0` release predates the publishing workflow and must not be rebuilt or replaced.
- [x] 2026-07-22: Recreated the local environment and passed `make verify` with 164 tests and
  93.06% combined coverage, mutation testing for all 2,047 generated mutations (1,625 killed,
  422 survivors), the deterministic 2,000-trace benchmark, and two additional complete test
  runs.
- [x] 2026-07-22: Built and inspected exactly one `0.1.1` wheel and sdist. Strict Twine,
  archive/content verification, tag/version identity, and isolated-wheel CLI checks passed.
  The local evidence hashes are
  `c01fa9d13e7765eee263ebeb6b4b66246c74ee8b525aa8c75916ebbb93f92bc7` for the wheel and
  `3e63cdbca0f67f016630acb53e4877c7e1aa3eab1bceaa4800b86d8fb4325dec` for the sdist.
  The release workflow will rebuild once and record the distinct exact bytes it publishes.
- [x] 2026-07-22: Reviewed and squash-merged release-candidate
  [PR #16](https://github.com/GermanGerken/journeygraph/pull/16) as
  `948eccab276eac42ecb0cd1f3ce0600354eb4d02`; all nine PR checks passed.
- [x] 2026-07-22: Reconfirmed the pending PyPI publisher in the signed-in account and activated
  [ruleset 19561684](https://github.com/GermanGerken/journeygraph/rules/19561684), which prevents
  updates and deletion of `v*` tags.
- [x] 2026-07-22: With separate owner authorization, published
  [GitHub Release `v0.1.1`](https://github.com/GermanGerken/journeygraph/releases/tag/v0.1.1)
  from the merged commit and approved only the protected `pypi` environment after the exact
  build-and-verification job passed.
- [x] 2026-07-22: [Release run 29931111859](https://github.com/GermanGerken/journeygraph/actions/runs/29931111859)
  published through OIDC and passed remote-hash plus fresh-install verification. The published
  SHA-256 digests are `79835cb57084aeb785baff8c0e061239fcc4a984e385433d1e529c5df765df00`
  for `journeygraph-0.1.1-py3-none-any.whl` and
  `25729f54e87b1fd862cf362e20d0b8c693b30620367792f1bca99f7e37f8b899` for
  `journeygraph-0.1.1.tar.gz`.
- [x] 2026-07-22: Independently installed `journeygraph==0.1.1` from the production index with
  cache disabled, confirmed import and CLI version `0.1.1`, ran `journeygraph --help`, and
  generated the documented five-file demo with 45 events across 9 traces.

## Decision log

- **Separate PRs for #4 and #5.** OIDC publication and real-trace research have independent
  trust boundaries and should not block or obscure each other's review.
- **Use `release.published`, not tag push or manual dispatch.** A GitHub Release is an explicit
  maintainer event, while the protected environment remains the final approval boundary.
- **Build once, verify, then hand off.** Release verification calls `verify_wheel.py` directly
  after the final build so it tests the bytes that will be uploaded.
- **Bind to the event commit, not a mutable tag lookup.** Both checkouts use `github.sha`; the
  release tag name is an independent version assertion and cannot redirect the running jobs.
- **Hash downloaded bytes before installation.** PyPI JSON is checked first, then the exact
  official wheel URL is downloaded, hashed again, and installed locally so verification cannot
  drift between metadata lookup and installation.
- **Pin every release action by SHA.** Moving tags are inappropriate in a credential-equivalent
  workflow; Dependabot can propose reviewed pin updates.
- **Do not use `skip-existing`.** A filename collision is a release error, not a condition to
  hide.
- **Keep README installation unchanged until verified publication.** A pending publisher and
  workflow were not evidence of PyPI availability; the successful release and independent
  fresh-install check now permit the post-release documentation update.
- **Use `0.1.1` for the corrective publication.** Changes since `v0.1.0` preserve the
  public analytical contracts while fixing input boundaries and restoring release, mutation,
  and native Windows verification. Reusing `v0.1.0` would replace historical release intent
  and cannot trigger the already-missed `release.published` workflow event.

## Outcomes and remaining work

The repository implementation, owner controls, separately authorized `v0.1.1` release, OIDC
publication, remote hash comparison, and independent fresh-install demo are complete. The
post-release documentation change makes the verified PyPI installation path authoritative;
issue #4 can close when that protected-main PR is merged.
