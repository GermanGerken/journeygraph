# Release Procedure

JourneyGraph uses GitHub tags/releases for authorized alpha source and wheel artifacts. It has
no configured package-registry publication workflow. A GitHub release is not evidence that a
package was published to PyPI or another registry.

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
make wheel-smoke
```

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

## Publication

No package registry, signing service, release automation, or credential flow is declared in
this repository yet. Establish and review that process separately before the first publication.
Do not improvise a production upload command or copy credentials into shell history, files,
issues, CI logs, or documentation.

Once an authorized publication mechanism exists:

1. Reconfirm the exact commit and clean working tree.
2. Create only the authorized tag.
3. Publish only the inspected artifacts to the authorized destination.
4. Verify the remote artifact and metadata independently.
5. Create release notes from the reviewed changelog.
6. Record commands, artifact hashes, tag, publication URL, and verification evidence in the
   execution plan or release record.

If any post-publication verification fails, stop. Do not overwrite history or silently replace
artifacts. Document the issue and choose an explicit corrective release or withdrawal process.

## Post-release review

- Run the documented fresh-install quickstart against the published artifact.
- Confirm links, license metadata, and package contents.
- Confirm no private fixture, absolute path, secret, or unsupported claim was published.
- Update the changelog comparison links only after the remote tag exists.
- Record known limitations and the next supported branch/version in [Security Policy](../SECURITY.md).
