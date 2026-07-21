# JourneyGraph Product Brief

## Product statement

JourneyGraph is a local-first graph analytics toolkit that turns event streams and AI-agent traces into explainable journey graphs.

It is intended to discover recurring execution paths, retries, loops, failure points, success cohorts, and relationships between behavior, latency, cost, and outcomes across many traces.

## Core distinction

Tracing and observability tools primarily help engineers inspect what happened during a particular execution. JourneyGraph will focus on structural patterns across a collection of executions.

JourneyGraph should complement existing tracing platforms. It should not become another trace collector, prompt manager, hosted observability service, or generic LLM wrapper.

## Primary users

- AI and agent engineers analyzing tool use and failure modes;
- data scientists exploring graph-based behavioral patterns;
- product analysts studying nonlinear user journeys;
- product managers comparing successful and unsuccessful flows;
- researchers evaluating agent strategies.

## Example journey

```text
request
  -> intent classification
  -> document retrieval
  -> model generation
  -> tool call
  -> validation
  -> success
```

A problematic journey could instead contain repeated retrieval, failed tools, retries, or a human handoff. JourneyGraph should make these aggregate patterns visible and measurable.

## MVP direction

The MVP should ingest a small, documented set of event and trace formats, normalize them into a vendor-neutral domain model, construct directed transition graphs, and report:

- common paths and transitions;
- entry and terminal steps;
- loops and repeated actions;
- failure and drop-off points;
- outcome rates by path or cohort;
- latency, token, and cost summaries when available;
- data-quality and privacy warnings.

The first release should include a deterministic synthetic AI-agent dataset and a complete local demonstration.

## Product principles

### Local-first

Core analysis must run locally without a cloud account, hosted database, or model API key.

### Privacy-aware by default

The canonical format should use allowlisted operational metadata. Raw prompts, responses, document bodies, personal identifiers, and secrets should not be required or emitted by default.

### Explainable and deterministic

Users must be able to understand how paths, loops, cohorts, and metrics were produced. Identical inputs and configuration should produce equivalent outputs.

### Vendor-neutral

Provider-specific importers should translate data into a small canonical model. The analytical core should not depend on one vendor or framework.

### Honest positioning

The project must not call association causation, present clusters as ground truth, claim compatibility without tests, or advertise prediction before a leakage-safe predictive workflow exists.

## Initial non-goals

- collecting traces from running applications;
- a hosted SaaS product;
- authentication or billing;
- a graph database;
- real-time streaming;
- GNNs or deep-learning models;
- causal attribution;
- LLM-as-a-judge;
- automatic prompt optimization;
- remote telemetry;
- multiple shallow integrations.

## Open-source positioning

Working repository description:

> Local-first graph analytics for AI agent traces. Find recurring paths, loops, failures, and success patterns across event data.

Candidate discovery topics, to be retained only when implemented accurately:

- `ai-agents`
- `llm-observability`
- `opentelemetry`
- `openinference`
- `graph-analytics`
- `trace-analysis`
- `journey-analysis`
- `agent-evaluation`
- `python`

## Planning requirement

Product implementation must begin from a self-contained ExecPlan stored under `docs/exec-plans/`. The plan must define the canonical schema, architecture, CLI contracts, privacy boundary, milestones, test strategy, acceptance criteria, and repository harness before implementation proceeds.

