"""Seeded simulation of a support agent, used to reproduce the diff/check example.

Synthetic by construction: it shows what JourneyGraph reports for a known, injected
regression. It is not evidence about any real system.

    python simulate_agent.py baseline  out/baseline.jsonl
    python simulate_agent.py candidate out/candidate.jsonl
"""

from __future__ import annotations

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

TRACES = 600
INTENTS = (("refund", 0.3), ("order_status", 0.45), ("product_question", 0.25))
SEEDS = {"baseline": 20261111, "candidate": 20261112}
START = datetime(2026, 11, 1, tzinfo=UTC)

Record = dict[str, object]


class Trace:
    """Collects the steps of one simulated request in chronological order."""

    def __init__(self, rng: random.Random, variant: str, index: int, intent: str) -> None:
        self.rng = rng
        self.trace_id = f"{variant}-{index:04d}"
        self.metadata = {"cohort": intent, "version": variant}
        self.moment = START + timedelta(seconds=index * 30)
        self.steps: list[Record] = []

    def add(self, op: str, component: str, low: int, high: int, **extra: object) -> Record:
        duration = self.rng.randint(low, high)
        record: Record = {
            "schema_version": "1.0",
            "trace_id": self.trace_id,
            "step_id": f"s{len(self.steps):02d}",
            "timestamp": self.moment.isoformat().replace("+00:00", "Z"),
            "operation_type": op,
            "component": component,
            "duration_ms": duration,
            "status": "ok",
            "metadata": dict(self.metadata),
            **extra,
        }
        if self.steps:
            record["parent_step_id"] = self.steps[-1]["step_id"]
        self.steps.append(record)
        self.moment += timedelta(milliseconds=duration + 1)
        return record

    def llm(self) -> Record:
        tokens_in, tokens_out = self.rng.randint(600, 1800), self.rng.randint(80, 400)
        return self.add(
            "llm",
            "planner",
            400,
            2200,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cost_usd=round(tokens_in * 3e-6 + tokens_out * 15e-6, 6),
        )


def simulate_trace(rng: random.Random, variant: str, index: int) -> list[Record]:
    candidate = variant == "candidate"
    intent = rng.choices([name for name, _ in INTENTS], [weight for _, weight in INTENTS])[0]
    trace = Trace(rng, variant, index, intent)
    trace.add("request", "user_message", 1, 5)
    trace.add("router", "intent_router", 10, 40)
    outcome = "success"
    if intent == "product_question":
        trace.add("retrieval", "knowledge_search", 40, 180)
        trace.llm()
        if rng.random() < 0.12:  # weak retrieval, one more round
            trace.add("retrieval", "knowledge_search", 40, 180)
            trace.llm()
            if rng.random() < 0.4:
                outcome = "handoff"
    elif intent == "order_status":
        trace.llm()
        tool = trace.add("tool", "order_lookup", 60, 300)
        if rng.random() < 0.05:
            tool["status"] = "error"
            trace.add("tool", "order_lookup", 60, 300)  # retry
        trace.llm()
    else:  # refund
        trace.llm()
        trace.add("tool", "order_lookup", 60, 300)
        trace.llm()
        # The injected regression: the candidate planner re-checks policy in a loop
        # and the refund tool times out more often.
        rounds = 1 + (rng.choices([0, 1, 2], [0.35, 0.4, 0.25])[0] if candidate else 0)
        for _ in range(rounds):
            trace.add("tool", "policy_check", 30, 120)
            trace.llm()
        refund = trace.add("tool", "refund_api", 200, 900)
        if rng.random() < (0.22 if candidate else 0.06):
            refund["status"] = "error"
            refund["duration_ms"] = 5000
            retry = trace.add("tool", "refund_api", 200, 900)
            if rng.random() < 0.6:
                retry["status"] = "error"
                outcome = "failure"
        if outcome == "success":
            trace.llm()
    if outcome == "success" and rng.random() < 0.03:
        outcome = "dropoff"
    trace.add("validation", "answer_guard", 5, 30)
    trace.steps[-1]["outcome"] = outcome
    return trace.steps


def simulate(variant: str, path: str) -> None:
    rng = random.Random(SEEDS[variant])
    with Path(path).open("w", encoding="utf-8") as out:
        for index in range(TRACES):
            for record in simulate_trace(rng, variant, index):
                out.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in SEEDS:
        sys.exit("usage: python simulate_agent.py {baseline|candidate} OUTPUT.jsonl")
    simulate(sys.argv[1], sys.argv[2])
