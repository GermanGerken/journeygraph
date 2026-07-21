# Testing and Quality

JourneyGraph uses one repository `Makefile` as the canonical local quality interface. The
commands are designed for a fresh checkout and do not depend on IDE configuration.

## Environment setup

Python 3.11 or later is required.

```bash
make setup
```

`make setup` creates `.venv` and installs the editable project with development, mutation,
and optional Parquet dependencies. It upgrades pip inside that environment, so setup requires
access to the configured Python package index. Product tests themselves must not call external
services.

The repository's canonical development harness assumes a POSIX shell and virtual-environment
layout (`.venv/bin`). On native Windows, use WSL or translate the targets deliberately; native
PowerShell and Command Prompt commands are not currently a tested project interface.

## Canonical commands

| Command | Purpose |
| --- | --- |
| `make format` | Apply Ruff formatting and safe lint fixes to source, tests, and scripts. |
| `make format-check` | Verify formatting without changing files. |
| `make lint` | Run the configured Ruff rules. |
| `make typecheck` | Run strict mypy over `src` and `scripts`. |
| `make test-unit` | Run pure unit tests. |
| `make test-integration` | Run component-composition tests. |
| `make test-functional` | Run black-box installed-CLI acceptance tests. |
| `make test` | Run all three test layers. |
| `make coverage` | Run all tests with statement and branch coverage, enforce 90%, and write `artifacts/coverage.xml` plus `artifacts/junit.xml`. |
| `make build` | Build the source distribution and wheel. |
| `make wheel-smoke` | Build and test an isolated wheel installation, CLI help, and demo. |
| `make demo` | Write the deterministic demo to `artifacts/demo`, replacing prior demo artifacts. |
| `make docs-check` | Check documentation links, contracts, examples, and required files. |
| `make security` | Run dependency, static-security, and secret checks. |
| `make mutation` | Mutate selected normalization, graph, analytics, and reporting logic. |
| `make benchmark` | Run the deterministic local scenario with 2,000 traces and 12 steps. |
| `make verify` | Run formatting, lint, types, coverage, wheel smoke, docs, and security gates. |
| `make clean` | Remove the local `build`, `dist`, and `htmlcov` directories. |

`make verify` does not include mutation testing or benchmarking. Run those explicitly when
required by the execution plan or release checklist. Dependency auditing may need advisory
data from the configured environment; this is a development check, not product telemetry.

## Test layers

### Unit tests

`tests_unit/` covers pure algorithms and edge cases. Examples include category and path IDs,
node/edge weights, exact paths, retries, return loops, outcome reconciliation, cohorts,
missing metrics, percentiles, privacy rules, and escaping.

Unit tests use manually specified expected values rather than invoking production code to
generate their own oracle. Arrange, Act, and Assert phases are visually separated.

### Integration tests

`tests_integration/` composes real readers, normalization, graph, analytics, serialization,
and reporting through documented Python surfaces. It uses real temporary files and no network
or mocks of pure production logic.

Format claims require representative integration coverage. Optional Parquet tests may be
conditional only on the explicit optional dependency; they must decode a real Parquet file,
not a renamed JSON fixture.

### Functional tests

`tests_functional/` is the acceptance backbone. Tests locate and execute the installed
`journeygraph` console script in a subprocess. They do not import JourneyGraph modules or
patch production behavior. They provide real files, inspect stdout/stderr and exit codes,
parse JSON/HTML/XML artifacts, and verify semantic results.

Functional scenarios include linear and branching journeys, retry and loop behavior,
out-of-order input, duplicates, malformed and empty input, privacy exclusions, markup
injection, Unicode, and output-path safety. Installed-wheel smoke tests protect against
repository-relative imports and missing packaged data.

## Coverage policy

Combined statement and branch coverage must remain at least 90%:

```bash
make coverage
```

The threshold is a guardrail, not a substitute for behavior tests. Normalization, graph
construction, path and loop analysis, privacy filtering, serialization, and escaping require
explicit positive and negative cases regardless of the aggregate percentage.

Do not:

- lower thresholds to make a change pass;
- exclude meaningful branches broadly;
- delete negative behavior;
- assert only that a function was imported or returned a truthy value;
- mock the pure algorithm being tested;
- hide flakes with automatic reruns.

## Determinism and warnings

The test configuration treats warnings as errors. Tests control time, ordering, locale,
filesystem state, and randomness where those could affect results. Equivalent row
permutations must preserve normalized analytical meaning. Repeated analysis of the same
input and configuration must produce byte-equivalent deterministic JSON.

Source-order warnings can legitimately differ between differently ordered raw inputs.
Permutation tests may compare analytical meaning after excluding the warning and issue
collections, their aggregate count, and the raw input count; warning behavior is asserted
separately where it is part of the scenario.

## Regression workflow

For a user-visible defect:

1. Preserve the smallest sanitized reproducer.
2. Add a failing test at the highest useful public boundary, normally functional.
3. Confirm the test fails for the intended reason.
4. Fix the smallest responsible layer.
5. Run the focused unit/integration area.
6. Run the full verification suite, preferably twice before a release.

Never include a real prompt, response, trace, personal record, access token, or secret in a
fixture or captured log.

## Mutation and performance checks

Mutation testing targets deterministic ordering and deduplication, graph/path counts, loop
detection, outcomes, metadata filtering, and deterministic JSON/embedded-data serialization:

```bash
make mutation
```

Review surviving mutations individually. Add a test only when the mutation reveals a real
behavioral gap. Whole HTML/SVG renderers are outside the mutation scope; adversarial unit and
black-box parser tests cover their contextual escaping and non-executable output instead.

The benchmark is a local regression signal, not a universal performance claim:

```bash
make benchmark
```

It reports ingestion, normalization, a standalone graph diagnostic, full analysis (which
includes graph construction), report rendering, and an end-to-end total that excludes the
duplicated standalone graph diagnostic.

Record the dataset size, Python version, hardware, and command whenever publishing a result.
Do not advertise a threshold or comparison that was not measured reproducibly.

## Before reporting completion

Run the checks proportional to the change, then run:

```bash
make verify
```

Also review the diff for scope creep, secrets, copied service-specific configuration, dead
code, unsupported compatibility claims, and generated artifacts. Mutation and benchmark
results are reported separately when applicable.
