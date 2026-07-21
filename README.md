# JourneyGraph

**Local-first graph analytics for AI agent traces and event data.**

JourneyGraph is an open-source project for turning collections of AI-agent traces and product events into explainable journey graphs. Its goal is to reveal recurring paths, loops, failure points, and success patterns across many executions—not only inside one trace.

> **Project status:** design phase. The product architecture and implementation plan are being prepared before development begins.

## Why JourneyGraph?

Tracing tools are excellent for inspecting an individual execution. JourneyGraph is intended to answer a different set of questions across a population of traces:

- Which execution paths occur most often?
- Where do agents retry, loop, or fail?
- Which paths are associated with successful outcomes?
- How do latency, token usage, and cost differ between paths?
- Which behavior patterns appear across many sessions?

## Flagship use case

The first use case will focus on AI agents and LLM applications:

```text
user request -> router -> retrieval -> model -> tool -> validation -> outcome
```

JourneyGraph will analyze trace and event exports locally and produce an explainable graph of aggregate behavior.

## Principles

- **Local-first:** core analysis should not require a hosted service or API key.
- **Privacy-aware:** raw prompts, responses, and personal data are not required by default.
- **Explainable:** results should be inspectable and reproducible.
- **Vendor-neutral:** the internal model should not depend on one tracing provider.
- **Evidence-backed:** public claims must correspond to tested functionality.

## Planned first milestone

The initial MVP is expected to provide:

- a canonical event and trace schema;
- validation, normalization, ordering, and redaction;
- directed journey-graph construction;
- path, loop, failure, outcome, latency, and cost analysis;
- a local CLI;
- machine-readable output and a human-readable report;
- deterministic synthetic AI-agent traces;
- automated tests and reproducible quality checks.

The exact scope will be finalized in an approved execution plan before product code is written.

## Documentation

- [Product brief](docs/product-brief.md)
- An implementation ExecPlan will be added under `docs/exec-plans/`.

## Contributing

JourneyGraph is not yet accepting implementation contributions while its first execution plan is being prepared. Contribution guidance and issue templates will be added as part of the repository harness.

## License

Licensed under the [Apache License 2.0](LICENSE).

