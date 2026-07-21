# Release Procedure

JourneyGraph uses GitHub tags/releases for authorized alpha source and wheel artifacts. The
repository contains a PyPI Trusted Publishing workflow, but repository code alone does not
activate it. Publication additionally requires an exact PyPI publisher registration and a
protected GitHub `pypi` environment configured by the repository owner. A GitHub release is
not, by itself, evidence that a package was published to PyPI or another registry.

Publishing, pushing, tagging, merging, or creating a release requires explicit repository-owner
authorization. Local implementation approval does not grant release authority.

## Release prerequisites

Before proposing a release:

1. Confirm the approved execution plan and its progress, decisions, discoveries, outcomes,
   limitations, branch, commits, and Git status are current.
2. Confirm every compatibility, security, privacy, test, and performance statement is backed
   by current evidence.
3. Confirm the intended version and supported Python versions.
4. Review dependency versions and licenses from primary package metadata.
5. Update [CHANGELOG](../CHANGELOG.md) without inventing a release date or status.
6. Keep the version in `pyproject.toml` and `src/journeygraph/version.py` identical.
7. Confirm documentation examples and the README quickstart run from a fresh environment.
8. Obtain explicit authorization for the exact tag, remote, and publication destination.
9. Confirm the owner-only Trusted Publishing controls in the activation checkpoint below.

## Required local verification

From a clean checkout at the proposed release commit:

```bash
make setup
make verify
make mutation
make benchmark
```

`make verify` covers format checks, lint, strict types, the full test suite with 90% statement
and branch coverage, package build, isolated wheel smoke, documentation checks, dependency
audit, static security analysis, and secret scanning.

Mutation and benchmark commands remain separate. A benchmark result may be published only
with the command, dataset size, Python version, hardware, and observed measurement. Do not
turn one local result into a universal threshold or performance claim.

Run the full tests at least twice before final authorization to detect order dependence:

```bash
make test
make test
```

## Inspect build artifacts

Build outputs are created by:

```bash
make build
make dist-check
.venv/bin/python scripts/verify_wheel.py
```

`make dist-check` verifies strict package metadata, exact version identity, one wheel plus one
source distribution, archive paths, required packaged content, and embedded metadata. It also
writes `artifacts/release-sha256.txt`. Run it only after `make build`; do not rebuild between
inspection and publication. The direct verifier installs that exact wheel; unlike the general
`make wheel-smoke` development target, it does not invoke `make build` again.

Before publication, inspect the source distribution and wheel contents. Confirm that they
include the license, typed-package marker, packaged demo data, and intended source files, and
exclude local traces, reports, credentials, caches, coverage files, virtual environments,
and unrelated generated artifacts.

Install the wheel into a new isolated environment and repeat at minimum:

```bash
journeygraph --help
journeygraph validate --help
journeygraph analyze --help
journeygraph demo --output-dir journeygraph-demo
```

Inspect all generated artifacts, not only command exit codes.

## Version and changelog

JourneyGraph uses semantic versioning as an intent, with additional caution while the public
surface is alpha:

- Patch: compatible defect or documentation correction.
- Minor: additive functionality or a deliberately versioned analytical contract change.
- Major: incompatible public schema, CLI, API, privacy, or identity behavior after stability.

During alpha, a minor version may still contain breaking changes, but each must be called out
prominently in the changelog with migration guidance. Never silently change node/path identity,
ordering, outcome reconciliation, privacy filtering, or deterministic output meaning.

Move verified changelog entries from `Unreleased` into a version heading only when the release
is actually authorized. Add the real release date at publication time.

## Trusted Publishing activation checkpoint

The workflow in `.github/workflows/release.yml` uses GitHub's short-lived OIDC identity; it has
no PyPI password or long-lived API token. Before the first authorized publication, the owner
must complete and independently review all of these external controls:

1. Secure the PyPI owner account with a verified email, at least two 2FA methods, and stored
   recovery codes.
2. Register the pending or existing PyPI publisher with project `journeygraph`, owner
   `GermanGerken`, repository `journeygraph`, workflow `release.yml`, and environment `pypi`.
3. Create a GitHub environment named exactly `pypi`, require manual approval, and restrict
   deployment tags to the authorized `v*` pattern. No environment secret is required.
4. Ensure the approval policy is usable. A solo maintainer must not enable
   prevent-self-review unless a second authorized reviewer is available.
5. Review every pinned action commit and the release workflow as credential-equivalent code.
6. Protect authorized release tags from mutation and deletion through a reviewed tag ruleset.

Do not configure these controls casually, improvise a production upload command, or copy
credentials into shell history, files, issues, CI logs, or documentation. The exact fields are
also recorded in the [Trusted Publishing execution plan](exec-plans/pypi-trusted-publishing.md).

## Authorized publication flow

The workflow runs only when an authorized GitHub Release is published. It does not run on pull
requests, tag pushes, or manual dispatches. Because `v0.1.0` predates the workflow, publishing or
editing that existing release will not be used to backfill PyPI; use a separately reviewed new
version.

For an authorized release:

1. Reconfirm the exact commit, clean working tree, approved version, changelog, and green CI.
2. Run the local verification above and record the exact candidate SHA-256 hashes.
3. Obtain explicit authorization for the exact tag and GitHub Release.
4. Create only that tag and publish only that GitHub Release.
5. Review the build job's evidence before approving the protected `pypi` environment.
6. The publish job downloads the already verified artifacts and exchanges its OIDC identity
   directly with PyPI; it must not rebuild them.
7. The post-publication job compares PyPI filenames and hashes with the build manifest, installs
   the exact version from the official index in a fresh environment, and exercises the CLI demo.
8. Record the workflow URL, artifact hashes, tag, PyPI URL, and verification result in the
   execution plan or release record.

The README checkout installation remains authoritative until this entire path has succeeded.
Only then may documentation claim `pip install journeygraph` availability.

If any post-publication verification fails, stop. Do not overwrite history or silently replace
artifacts. Document the issue and choose an explicit corrective release or withdrawal process.

## Post-release review

- Run the documented fresh-install quickstart against the published artifact.
- Confirm links, license metadata, and package contents.
- Confirm no private fixture, absolute path, secret, or unsupported claim was published.
- Update the changelog comparison links only after the remote tag exists.
- Record known limitations and the next supported branch/version in [Security Policy](../SECURITY.md).
