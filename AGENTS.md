# Repository guidance

Read `README.md`, `docs/product-brief.md`, and the active plan under `docs/exec-plans/`
before changing product behavior. Keep a significant feature's approved ExecPlan current with
progress, discoveries, decisions, and outcomes.

## Product invariants

- Keep the analytical core local-first, deterministic, explainable, and vendor-neutral.
- Do not require an LLM, hosted service, external API key, or telemetry for core functionality.
- Do not require or emit raw prompts, responses, personal data, document contents, or secrets
  by default. Preserve the metadata allowlist and permanent sensitive-key denylist.
- Keep format importers separate from canonical domain, graph, analytics, and reporting logic.
- Treat events/spans, traces/sessions, paths, aggregate graphs, and cohorts as distinct concepts.
- Describe outcome relationships as associations, never causation or prediction.
- Do not claim compatibility, performance, security, or test status without current evidence.

## Testing rules

- Deliver tests with every user-visible behavior change.
- Functional tests are the acceptance backbone: execute the real installed `journeygraph`
  command as a subprocess, use real files, and assert observable output. They must not import
  JourneyGraph internals, monkeypatch production logic, or require network access.
- Integration tests compose documented public APIs with real temporary files.
- Unit tests cover pure algorithms and difficult edge cases; they do not replace CLI coverage.
- Write Arrange, Act, Assert phases. Add negative paths and the smallest useful regression
  before fixing a discovered user-visible defect.
- Combined statement and branch coverage must stay at or above 90%. Do not game exclusions or
  weaken the threshold.

## Canonical commands

Use the `Makefile`; CI invokes the same targets:

```bash
make setup
make format
make format-check
make lint
make typecheck
make test-unit
make test-integration
make test-functional
make coverage
make build
make wheel-smoke
make demo
make docs-check
make security
make mutation
make benchmark
make verify
```

## Engineering expectations

- Preserve user changes and avoid unrelated edits or destructive Git operations.
- Verify unstable technical facts from current primary documentation.
- Keep pure transformations separate from filesystem, rendering, and CLI side effects.
- Keep public schemas and CLI/output contracts versioned and documented.
- Keep public documentation in clear professional English.
- Never weaken tests or remove required behavior merely to make a check pass.
- Do not push, publish, release, tag, merge, or change remote settings without explicit
  authorization.
