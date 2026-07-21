# Security Policy

JourneyGraph is an early local-first alpha. It processes potentially sensitive trace exports and
writes local artifacts, but it is not a sandbox, malware scanner, anonymization service, or
defense against deliberately resource-exhausting input.

## Supported versions

There is no published stable release or tagged support line yet. Security fixes are currently
developed on the default branch for the forthcoming `0.1.x` alpha. A version table will be added
when an actual release exists; the version in package metadata alone does not establish support.

Do not assume that an unreleased checkout receives backports or a fixed support lifetime.

## Reporting a vulnerability

Do not open a public issue containing exploit instructions, private traces, personal data,
credentials, or a proof of concept that could put users at risk.

Preferred private-first process:

1. Open the repository's **Security** tab.
2. If **Report a vulnerability** is available, use GitHub private vulnerability reporting.
3. Include the affected version or commit, platform and Python version, impact, prerequisites,
   minimal sanitized reproduction, and a suggested mitigation when known.

If private vulnerability reporting is not available, open a public issue containing only a
request for a private security channel and a high-level, non-exploitable description. Do not
include sensitive details. The repository does not currently publish a security email address;
no third-party address should be assumed to represent the project.

For dependency vulnerabilities, identify the package, affected range, advisory identifier, and
whether it is a runtime, optional, development, or build dependency.

## What to expect

The project will acknowledge and assess reports as maintainer availability permits. No response
or remediation deadline is promised while the project has no published support program. A valid
report may lead to a private fix, additional tests, documentation, a release, or a disclosure
coordinated through the hosting platform.

Please do not publish details until an authorized maintainer confirms that disclosure is safe.
The project will credit reporters only with their consent.

## Security-relevant boundaries

JourneyGraph's product path:

- reads user-selected local files;
- performs no product telemetry or network request;
- requires no cloud account, database, API key, LLM, prompt, or response;
- filters metadata by allowlist plus a permanent sensitive-key denylist;
- escapes untrusted HTML and SVG content;
- rejects selected traversal, direct symlink-root, overwrite, and input-collision cases;
- writes output through temporary sibling files and atomic replacement where supported.

Important limitations:

- allowlisted values, labels, identifiers, timestamps, and rare paths may still be sensitive;
- filtering is not anonymization or content-based secret detection;
- the complete multi-file artifact set is not transactionally published;
- parent-directory and filesystem behavior remains platform-dependent;
- accepted input is substantially materialized in memory;
- no protection is claimed against hostile files intended to exhaust memory, CPU, or disk;
- optional Parquet support adds PyArrow to the runtime environment;
- experimental OTLP/JSON support is a narrow file importer, not a network receiver.

See [Privacy and Threat Model](docs/privacy.md) for the complete operating guidance.

## Out of scope for private vulnerability reporting

The following are normally better handled as public bugs or proposals when they contain no
sensitive detail:

- unsupported formats or provider-specific export variants;
- requests for authentication, hosted operation, or remote collection;
- performance observations without a security impact;
- compatibility claims not made by the project;
- social-engineering requests for credentials or access;
- reports based only on an automated scanner without an affected path or reproducible impact.

Never test a report against another person's data or system without permission.

## Secure development checks

The canonical local security target is:

```bash
make security
```

It runs a local dependency audit, Bandit over `src`, and a secret scan against tracked files.
The completion gate also includes tests, branch coverage, strict types, package build, installed
wheel smoke, and documentation checks:

```bash
make verify
```

Automated tools are guardrails. They do not replace review of trust boundaries, escaping,
privacy filtering, deterministic output, filesystem behavior, or dependency changes.

## Handling security fixes

Security fixes should include a sanitized regression test, avoid echoing sensitive values in
errors, preserve local-first behavior, and update this policy, privacy documentation, changelog,
and release notes as needed. Do not weaken tests or conceal a known limitation behind a broad
exclusion.

Publishing or tagging a security release requires explicit repository-owner authorization and
the [Release Procedure](docs/releasing.md).
