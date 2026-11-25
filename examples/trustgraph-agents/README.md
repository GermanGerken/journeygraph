# Example: analyzing TrustGraph agent sessions

[TrustGraph](https://github.com/trustgraph-ai/trustgraph) records every agent session as
explainability provenance in the named graph `urn:graph:retrieval`. Its own tools show one
session at a time. This example converts those records into JourneyGraph canonical JSON Lines,
so you can look across many sessions and compare two agent configurations with
`journeygraph diff`.

The converter is an example script, not a supported JourneyGraph input format. It was written
against the TrustGraph source at commit `17e5d74` (12 November 2026) and checked on 24 November
2026 against a local TrustGraph 3.0.0rc7 deployment (Docker Compose), with the exporter below and
about 400 real agent sessions.

## Run it on synthetic data

**The data below is synthetic.** `make_synthetic_triples.py` writes seeded triples with the
entity types, predicates, URI patterns, and `wasDerivedFrom` links that TrustGraph's agent
provenance builders produce. No TrustGraph instance generated them, and the numbers say
nothing about real TrustGraph agents. The candidate variant has an injected regression: its
`knowledge_query` tool fails more often, the agent retries it, and some sessions run out of
iterations before a final answer.

From this directory, with `journeygraph` installed:

```bash
mkdir -p out
python make_synthetic_triples.py baseline  out/baseline.retrieval.jsonl
python make_synthetic_triples.py candidate out/candidate.retrieval.jsonl
python trustgraph_to_journeygraph.py out/baseline.retrieval.jsonl  out/baseline.jsonl  --version baseline
python trustgraph_to_journeygraph.py out/candidate.retrieval.jsonl out/candidate.jsonl --version candidate
journeygraph diff out/baseline.jsonl out/candidate.jsonl --output-dir out/diff
```

Each variant has 300 top-level sessions: about 80% ReAct, 10% plan-then-execute, and 10%
supervisor sessions with two sub-agents each. The converter writes 2,099 baseline and 2,320
candidate events. In the candidate, 102 of 339 `knowledge_query` calls fail, against 11 of 232
in the baseline, and 15 sessions end without a final answer. `journeygraph diff` reports:

```text
tool:knowledge_query error-event rate moved from 5% to 30% (+25 percentage points).
```

## Run it on a TrustGraph deployment

1. Export the retrieval graph. Either use the bundled exporter, which needs the TrustGraph
   Python client (`pip install trustgraph-base`) and keeps literal types intact:

   ```bash
   python export_retrieval_graph.py out/retrieval.jsonl --url http://localhost:8888/
   ```

   or save the output of TrustGraph's own CLI:

   ```bash
   tg-show-graph -g urn:graph:retrieval -l 1000000 > out/retrieval.txt
   ```

   `tg-show-graph` defaults to 10,000 triples, so set `-l` high enough.

2. Convert and analyze:

   ```bash
   python trustgraph_to_journeygraph.py out/retrieval.jsonl out/events.jsonl --version v2
   journeygraph analyze out/events.jsonl --output-dir out/report
   ```

### Compare two configurations on one deployment

Sessions from every flow land in the same retrieval graph. To compare two configurations, for
example two flows with different models, give each agent request its own `session_id` and
record which configuration it belongs to. The TrustGraph Python client passes extra keyword
arguments through to the request:

```python
import uuid
from trustgraph.api import Api

session_id = str(uuid.uuid4())
flow = Api("http://localhost:8888/", token=token).socket().flow("candidate-flow")
flow.agent(question, streaming=False, session_id=session_id)
# append f"urn:trustgraph:agent:{session_id}" to candidate.sessions.txt
```

Then export once and convert each list separately:

```bash
python trustgraph_to_journeygraph.py out/retrieval.jsonl out/baseline.jsonl \
  --version baseline --sessions baseline.sessions.txt
python trustgraph_to_journeygraph.py out/retrieval.jsonl out/candidate.jsonl \
  --version candidate --sessions candidate.sessions.txt
journeygraph diff out/baseline.jsonl out/candidate.jsonl --output-dir out/diff
```

`--sessions` takes one top-level session URI or bare id per line; sub-agent sessions follow their
parent. When you switch a flow's model, set both `llm-model` and `llm-rag-model`: the agent
reasons through the RAG model, and setting only `llm-model` with `tg-start-flow` left it
unchanged in our run. The `model` metadata on each `agent_llm` event shows which model actually
ran.

The converter detects the input format from the first line. It prints a summary of traces,
sessions, and events to standard error, and exits with code 1 when it finds no agent sessions.

## How TrustGraph entities become events

| TrustGraph entity | `operation_type` | `component` | Fields carried over |
| --- | --- | --- | --- |
| Agent Question (top-level session) | `request` | `agent_question` | session start time |
| Agent Question (sub-agent session) | `agent` | `subagent` | own start time |
| PatternDecision | `router` | `pattern:<pattern>` | pattern as metadata `workflow` |
| Analysis (think/act cycle) | `llm` | `agent_llm` | `llmDurationMs`, tokens, model |
| Observation (tool result) | `tool` | tool name from its Analysis | `toolDurationMs`, `tg:Error` as `status: error` |
| Plan / Decomposition | `llm` | `planner` / `decomposer` | tokens, model |
| StepResult / Finding | `agent` | `plan_step` / `subagent_finding` | tokens |
| Conclusion / Synthesis | `outcome` | `answer:<terminationReason>` | outcome, tokens, model |

Sub-agent sessions created by a supervisor are folded into their parent's trace, so one trace
is one user request. Thought entities and GraphRAG or DocumentRAG questions are skipped.

When a tool runs a GraphRAG or DocumentRAG query, TrustGraph derives the Observation from that
query's Synthesis instead of from the Analysis that called the tool. The converter attaches such
an Observation to its own Analysis so the trace stays connected.

A ReAct step whose output TrustGraph could not parse is recorded with the action
`__parse_error__` and becomes a `tool` event with that component.

## Limits of the conversion

- **Step times are derived.** TrustGraph timestamps only the session start. Each step is placed
  at the session start plus the LLM and tool durations recorded before it. Steps with no
  recorded duration (routing, planning, answers) get `duration_ms: 0` and are spaced one
  microsecond apart to keep their order. Sub-agents that start together remain tied, and
  JourneyGraph reports them as `equal_timestamps` warnings.
- **Success means an answer was produced, not that it was correct.** TrustGraph's current
  termination reasons are `final-answer`, `plan-complete`, and `subagents-complete`; all
  three map to `success`, and any other reason maps to `failure`. A session that stopped
  without a Conclusion or Synthesis has no outcome event, and JourneyGraph counts it as
  `unknown`.
- **Nothing textual is copied.** Query text, thoughts, tool arguments, error messages, and
  answer documents are never written to the output. Tool names are copied as `component`, so
  check that your tool names are not sensitive before sharing reports.
- Up to TrustGraph 3.0.0rc7, `tg-show-explain-trace --format json` omits durations, errors,
  and tokens ([trustgraph#1219](https://github.com/trustgraph-ai/trustgraph/pull/1219) adds
  them), which is why this example reads the raw retrieval graph instead.
- A session that failed in the gateway or service (for example, a lost broker connection)
  may stop without an outcome. It appears as `unknown`, not as `failure`.
