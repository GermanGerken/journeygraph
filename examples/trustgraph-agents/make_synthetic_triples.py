"""Write seeded, synthetic TrustGraph agent explainability triples for this example.

**The data is synthetic.** No TrustGraph instance produced it. The triples follow the
entity types, predicates, URI patterns, and ``wasDerivedFrom`` links that TrustGraph's
``trustgraph.provenance.agent`` builders write to ``urn:graph:retrieval`` (checked against
the TrustGraph source at commit 17e5d74, 12 November 2026), so the converter can be exercised
without a running deployment. The numbers say nothing about real TrustGraph agents.

The candidate variant has an injected regression: its ``knowledge_query`` tool fails more
often, the agent retries it, and more sessions stop before a final answer.

    python make_synthetic_triples.py baseline  out/baseline.retrieval.jsonl
    python make_synthetic_triples.py candidate out/candidate.retrieval.jsonl
    python make_synthetic_triples.py baseline  out/baseline.retrieval.txt --text
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

TG = "https://trustgraph.ai/ns/"
PROV = "http://www.w3.org/ns/prov#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
DERIVED_FROM = PROV + "wasDerivedFrom"

SESSIONS = 300
SEEDS = {"baseline": 20261121, "candidate": 20261122}
START = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
MODEL = "synthetic-model-1"
MAX_ITERATIONS = 4
# Probability that a knowledge_query call fails, per variant.
KNOWLEDGE_QUERY_ERROR = {"baseline": 0.04, "candidate": 0.30}

Triple = dict[str, dict[str, str]]


def iri(value: str) -> dict[str, str]:
    return {"t": "i", "i": value}


def lit(value: object) -> dict[str, str]:
    return {"t": "l", "v": str(value)}


class Writer:
    def __init__(self) -> None:
        self.triples: list[Triple] = []

    def add(self, subject: str, predicate: str, obj: dict[str, str]) -> None:
        self.triples.append({"s": iri(subject), "p": iri(predicate), "o": obj})

    def entity(self, uri: str, *types: str, label: str, derived_from: str | None) -> None:
        self.add(uri, RDF_TYPE, iri(PROV + "Entity"))
        for local in types:
            self.add(uri, RDF_TYPE, iri(TG + local))
        self.add(uri, RDFS_LABEL, lit(label))
        if derived_from:
            self.add(uri, DERIVED_FROM, iri(derived_from))

    def tokens(self, uri: str, rng: random.Random, low: int, high: int) -> None:
        self.add(uri, TG + "inToken", lit(rng.randint(low, high)))
        self.add(uri, TG + "outToken", lit(rng.randint(40, 300)))
        self.add(uri, TG + "llmModel", lit(MODEL))


def session_start(w: Writer, session: str, moment: datetime, parent: str | None) -> None:
    w.entity(session, "Question", "AgentQuestion", label="Agent Question", derived_from=parent)
    w.add(session, PROV + "startedAtTime", lit(moment.isoformat().replace("+00:00", "Z")))
    w.add(session, TG + "query", lit("synthetic question"))


def react_session(
    w: Writer,
    rng: random.Random,
    variant: str,
    session: str,
    moment: datetime,
    parent: str | None = None,
    *,
    with_decision: bool = True,
) -> datetime:
    """Write a ReAct session and return the moment it ends."""
    session_start(w, session, moment, parent)
    if with_decision:
        decision = f"{session}/pattern-decision"
        w.entity(decision, "PatternDecision", label="Pattern: react", derived_from=session)
        w.add(decision, TG + "pattern", lit("react"))
        w.add(decision, TG + "taskType", lit("general"))

    previous: str | None = None
    planned = rng.choice(
        [
            ["knowledge_query"],
            ["knowledge_query", "calculator"],
            ["web_search", "knowledge_query"],
            ["web_search"],
        ]
    )
    iteration = 0
    finished = False
    while iteration < MAX_ITERATIONS:
        if not planned:
            finished = True
            break
        iteration += 1
        tool = planned[0]
        analysis = f"{session}/i{iteration}"
        w.entity(
            analysis,
            "Analysis",
            "ToolUse",
            label=f"Analysis: {tool}",
            derived_from=previous or session,
        )
        w.add(analysis, TG + "action", lit(tool))
        w.add(analysis, TG + "arguments", lit("{}"))
        for candidate in ("knowledge_query", "web_search", "calculator"):
            w.add(analysis, TG + "toolCandidate", lit(candidate))
        w.add(analysis, TG + "stepNumber", lit(iteration))
        llm_ms = rng.randint(600, 2400)
        w.add(analysis, TG + "llmDurationMs", lit(llm_ms))
        w.tokens(analysis, rng, 800, 4000)
        thought = f"{analysis}/thought"
        w.add(analysis, TG + "thought", iri(thought))
        w.entity(thought, "Reflection", "Thought", label="Thought", derived_from=analysis)

        observation = f"{analysis}/observation"
        w.entity(observation, "Observation", label="Observation", derived_from=analysis)
        tool_ms = {
            "knowledge_query": (300, 1500),
            "web_search": (800, 3000),
            "calculator": (5, 40),
        }[tool]
        failed = tool == "knowledge_query" and rng.random() < KNOWLEDGE_QUERY_ERROR[variant]
        duration = rng.randint(*tool_ms) * (4 if failed else 1)
        w.add(observation, TG + "toolDurationMs", lit(duration))
        if failed:
            w.add(observation, TG + "toolError", lit("synthetic timeout"))
            w.add(observation, RDF_TYPE, iri(TG + "Error"))
        else:
            planned.pop(0)
        previous = observation
        moment += timedelta(milliseconds=llm_ms + duration)

    if finished:
        final = f"{session}/final"
        w.entity(
            final, "Conclusion", "Answer", label="Conclusion", derived_from=previous or session
        )
        w.add(final, TG + "document", iri(f"{final}/doc"))
        w.add(final, TG + "terminationReason", lit("final-answer"))
        w.tokens(final, rng, 1500, 6000)
    return moment


def plan_session(w: Writer, rng: random.Random, session: str, moment: datetime) -> None:
    session_start(w, session, moment, None)
    decision = f"{session}/pattern-decision"
    w.entity(decision, "PatternDecision", label="Pattern: plan-then-execute", derived_from=session)
    w.add(decision, TG + "pattern", lit("plan-then-execute"))
    plan = f"{session}/plan"
    w.entity(plan, "Plan", label="Plan with 2 steps", derived_from=session)
    for goal in ("synthetic step one", "synthetic step two"):
        w.add(plan, TG + "planStep", lit(goal))
    w.tokens(plan, rng, 1000, 3000)
    previous = plan
    for index in range(2):
        step = f"{session}/step/{index}"
        w.entity(step, "StepResult", "Answer", label="Step result", derived_from=previous)
        w.add(step, TG + "planStep", lit(f"synthetic step {index}"))
        w.tokens(step, rng, 1000, 3000)
        previous = step
    synthesis = f"{session}/synthesis"
    w.entity(synthesis, "Synthesis", "Answer", label="Synthesis", derived_from=previous)
    w.add(synthesis, TG + "terminationReason", lit("plan-complete"))
    w.tokens(synthesis, rng, 1500, 5000)


def supervisor_session(
    w: Writer, rng: random.Random, variant: str, session: str, sid: str, moment: datetime
) -> None:
    session_start(w, session, moment, None)
    decision = f"{session}/pattern-decision"
    w.entity(decision, "PatternDecision", label="Pattern: supervisor", derived_from=session)
    w.add(decision, TG + "pattern", lit("supervisor"))
    decomposition = f"{session}/decompose"
    w.entity(
        decomposition,
        "Decomposition",
        label="Decomposed into 2 research threads",
        derived_from=session,
    )
    w.tokens(decomposition, rng, 800, 2000)
    findings: list[str] = []
    for index in range(2):
        child = f"urn:trustgraph:agent:{sid}-sub{index}"
        react_session(
            w,
            rng,
            variant,
            child,
            moment + timedelta(milliseconds=500),
            parent=decomposition,
            with_decision=False,
        )
        finding = f"{session}/finding/{index}"
        w.entity(finding, "Finding", "Answer", label="Finding", derived_from=decomposition)
        w.add(finding, TG + "subagentGoal", lit(f"synthetic goal {index}"))
        findings.append(finding)
    synthesis = f"{session}/synthesis"
    w.entity(synthesis, "Synthesis", "Answer", label="Synthesis", derived_from=findings[0])
    for extra in findings[1:]:
        w.add(synthesis, DERIVED_FROM, iri(extra))
    w.add(synthesis, TG + "terminationReason", lit("subagents-complete"))
    w.tokens(synthesis, rng, 2000, 6000)


def generate(variant: str) -> list[Triple]:
    rng = random.Random(SEEDS[variant])
    w = Writer()
    for index in range(SESSIONS):
        sid = f"{variant}-{index:04d}"
        session = f"urn:trustgraph:agent:{sid}"
        moment = START + timedelta(minutes=index)
        roll = rng.random()
        if roll < 0.8:
            react_session(w, rng, variant, session, moment)
        elif roll < 0.9:
            plan_session(w, rng, session, moment)
        else:
            supervisor_session(w, rng, variant, session, sid, moment)
    # A GraphRAG question in the same named graph; the converter must ignore it.
    rag = f"urn:trustgraph:question:{variant}-rag"
    w.entity(rag, "Question", "GraphRagQuestion", label="GraphRAG Question", derived_from=None)
    w.add(rag, PROV + "startedAtTime", lit(START.isoformat().replace("+00:00", "Z")))
    return w.triples


def main() -> int:
    if len(sys.argv) not in (3, 4) or sys.argv[1] not in SEEDS:
        print(__doc__, file=sys.stderr)
        return 2
    triples = generate(sys.argv[1])
    as_text = len(sys.argv) == 4 and sys.argv[3] == "--text"
    output = Path(sys.argv[2])
    with output.open("w", encoding="utf-8") as handle:
        for triple in triples:
            if as_text:  # the layout tg-show-graph prints: subject predicate object
                values = [term.get("i") or term.get("v", "") for term in triple.values()]
                handle.write(" ".join(values) + "\n")
            else:
                handle.write(json.dumps(triple, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
