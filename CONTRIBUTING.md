# Contributing to JourneyGraph

Thank you for helping improve JourneyGraph. The project is an early alpha and treats
analytical meaning, privacy boundaries, and public claims as part of the product contract.
Small, reviewable contributions with independent evidence are the easiest to evaluate.

By submitting a contribution, you agree that it is licensed under the repository's
[Apache License 2.0](LICENSE), unless a separate written agreement applies. Do not submit code,
fixtures, documentation, or media that you do not have the right to contribute.

## Before starting

Read:

- [Repository guidance](AGENTS.md)
- [Product brief](docs/product-brief.md)
- [Architecture](docs/architecture.md)
- [Data and Analysis Schemas](docs/schema.md)
- [Privacy and Threat Model](docs/privacy.md)
- [Testing and Quality](docs/testing.md)

Use an issue to discuss a substantial feature, compatibility claim, schema change, or
architectural change before implementation. Significant product work requires a self-contained,
repository-owner-approved execution plan under `docs/exec-plans/`. The plan must remain current
through implementation.

Discussion does not grant access to project-owned remotes or authorize a merge, release,
publication, remote-setting change, or external service action. Contributors may manage their
own forks; project mutations remain maintainer-controlled.

## Scope

JourneyGraph is local-first graph analytics for existing event and AI-agent trace exports. Good
contributions strengthen canonical ingestion, deterministic normalization, explainable graph
analysis, safe local reporting, tests, documentation, and repository quality.

The initial product does not include:

- trace collection or real-time streaming;
- hosted SaaS, accounts, authentication, or billing;
- a graph database;
- GNNs, deep learning, clustering presented as truth, or causal attribution;
- LLM-as-a-judge or automatic prompt optimization;
- remote telemetry;
- broad untested integrations.

Do not add an integration name, compatibility statement, benchmark, badge, production-readiness
claim, security claim, or privacy claim without tested evidence and documentation of the exact
boundary.

## Development setup

Python 3.11 or later is required. The canonical setup is:

```bash
make setup
```

This creates `.venv` and installs development, mutation, and optional Parquet dependencies.
The default runtime has no mandatory third-party dependency.

Useful focused commands are:

```bash
make format
make lint
make typecheck
make test-unit
make test-integration
make test-functional
```

Before requesting review, run:

```bash
make verify
```

Mutation testing and the deterministic benchmark are separate:

```bash
make mutation
make benchmark
```

See [Testing and Quality](docs/testing.md) for what each target covers and when the separate
checks are required.

## Architecture rules

- Translate provider-specific input into the canonical model inside `journeygraph.ingestion`.
- Keep provider and framework types out of graph, analytics, and reporting contracts.
- Keep graph and analytics transformations pure: no filesystem, environment, stdout, network,
  clock, or random-number side effects.
- Preserve chronological UTC ordering with `step_id` as the deterministic tie-breaker.
- Preserve versioned stable node/path identities unless an approved migration changes them.
- Keep format maturity narrow and honest.
- Prefer standard-library core behavior over new runtime dependencies.
- Record material assumptions and decisions in the active execution plan.

Avoid unrelated cleanup. Existing changes in a working tree belong to their author unless the
scope explicitly says otherwise.

## Tests

Add behavior tests with the implementation. Tests should:

- show Arrange, Act, and Assert phases;
- use manually specified expected values for analytical results;
- cover negative and warning paths, not only success;
- use real files and subprocesses at public boundaries;
- avoid mocking pure production logic;
- control ordering, time, randomness, locale, and filesystem state;
- assert determinism where the contract requires it;
- preserve the 90% combined statement and branch threshold without gaming exclusions.

For a defect, add the smallest useful regression reproducer and demonstrate the failure before
the fix. Functional tests must remain meaningful if the CLI implementation were replaced by
another language.

## Fixture privacy

Never commit a real trace, prompt, response, document, customer record, email address, access
token, API key, cookie, authorization header, or other secret. Use minimal deterministic
synthetic fixtures. Values intended to test redaction must be visibly synthetic and must not
match a real credential format by accident.

Before submission, inspect all source, fixtures, snapshots, generated reports, and logs. The
secret scanner is a guardrail, not permission to commit questionable data.

## Documentation

Public documentation must use clear professional English and match current behavior. Update the
relevant schema, CLI, privacy, architecture, testing, changelog, and release documentation when
a contract changes.

Link primary sources for unstable standards or dependency facts. For OTLP support, state the
accepted envelope and mapping rather than claiming general OpenTelemetry, OpenInference,
collector, or provider compatibility.

## Commits and pull requests

Prefer small Conventional Commit-style subjects, for example:

```text
fix: preserve exact nanosecond event ordering
test: cover retry then success outcome reconciliation
docs: clarify experimental OTLP JSON boundary
```

A pull request should include:

- the user-visible problem and intended outcome;
- the issue or approved execution plan, when required;
- the exact behavior and public contracts changed;
- privacy and security implications;
- tests added and commands run;
- documentation and changelog impact;
- known limitations and deliberate non-goals.

Do not weaken tests, remove required behavior, or broaden exclusions merely to make checks pass.
Do not include generated build, coverage, report, benchmark, or private-data artifacts unless a
reviewed requirement explicitly calls for a deterministic public asset.

## Review expectations

Review evaluates correctness, determinism, privacy, architecture boundaries, test independence,
documentation accuracy, scope, and maintainability. A green check is necessary but does not
replace review of the analytical oracle or public claim.

Maintainers may ask for a smaller scope, additional evidence, a plan update, or removal of an
unsupported claim. Changes are merged only by an authorized repository maintainer; contribution
does not guarantee acceptance or a release schedule.

## Conduct and security

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities
using the private-first process in [Security Policy](SECURITY.md), not a public issue containing
exploit details or sensitive data.
