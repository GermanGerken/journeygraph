# Repository guidance

JourneyGraph is currently in the design phase. Read `README.md` and `docs/product-brief.md` before proposing or making product changes.

## Planning gate

Before writing product code, create a self-contained ExecPlan under `docs/exec-plans/` and obtain the repository owner's approval. Keep the approved ExecPlan current during implementation, including progress, discoveries, decisions, and outcomes.

## Product invariants

- Keep the analytical core local-first and vendor-neutral.
- Do not require an LLM or external API key for core functionality.
- Do not require or emit raw prompts, responses, personal data, or secrets by default.
- Keep format-specific importers separate from the canonical domain and analytics layers.
- Prefer deterministic, explainable behavior over opaque complexity.
- Do not describe association as causation or unvalidated clustering as ground truth.
- Do not claim compatibility, performance, security, or test status without evidence.

## Engineering expectations

- Preserve existing user changes and avoid unrelated edits.
- Verify unstable technical facts from current primary documentation.
- Add tests for new behavior and run the relevant checks before reporting completion.
- Never weaken tests or remove required behavior merely to make a check pass.
- Record material assumptions and architectural decisions in the ExecPlan.
- Keep public documentation in clear professional English.
- Do not push, publish, create releases, or mutate remote settings without explicit authorization.

Canonical development commands and detailed review expectations will be added by the approved repository-harness milestone.

