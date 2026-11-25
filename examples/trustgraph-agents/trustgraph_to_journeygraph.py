"""Convert TrustGraph agent explainability triples into JourneyGraph canonical JSON Lines.

TrustGraph records every agent session as PROV-O entities in the named graph
``urn:graph:retrieval``: a Question, an optional PatternDecision, one Analysis per think/act
cycle with its Observation, and a final Conclusion or Synthesis. This script turns those
entities into one JourneyGraph event each, grouped into one trace per top-level session.

Input is either JSON Lines of TrustGraph wire triples (``export_retrieval_graph.py``) or the
plain-text output of ``tg-show-graph -g urn:graph:retrieval``. The format is detected from the
first non-blank line.

    python trustgraph_to_journeygraph.py retrieval.jsonl events.jsonl --version candidate

``--sessions FILE`` keeps only the listed top-level sessions, which lets one export of a
shared deployment be split into the configurations being compared.

Only operational fields are emitted: tool names, durations, token counts, model, pattern,
error flags, and termination reasons. Query text, thoughts, tool arguments, error messages,
and answer documents are never read into the output.

TrustGraph timestamps only the session start. Each step's timestamp is reconstructed as the
session start plus the recorded LLM and tool durations of the steps before it, so step times
are an approximation and should be described as derived. Steps with no recorded duration are
spaced one microsecond apart to keep TrustGraph's step order.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

TG = "https://trustgraph.ai/ns/"
PROV = "http://www.w3.org/ns/prov#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
DERIVED_FROM = PROV + "wasDerivedFrom"
STARTED_AT = PROV + "startedAtTime"
AGENT_PREFIX = "urn:trustgraph:agent:"

SUCCESS_REASONS = frozenset({"final-answer", "plan-complete", "subagents-complete"})
ORDERING_GAP = timedelta(microseconds=1)

Record = dict[str, object]


@dataclass
class Entity:
    uri: str
    types: set[str] = field(default_factory=set)
    props: dict[str, list[str]] = field(default_factory=dict)

    def first(self, predicate: str) -> str | None:
        values = self.props.get(predicate)
        return values[0] if values else None

    def integer(self, predicate: str) -> int | None:
        value = self.first(predicate)
        if value is None:
            return None
        try:
            return max(int(float(value)), 0)
        except ValueError:
            return None

    def is_a(self, local_name: str) -> bool:
        return TG + local_name in self.types


# --------------------------------------------------------------------------- input parsing


def _wire_value(term: object) -> str:
    """Return the IRI or literal value of a TrustGraph wire-format term."""
    if isinstance(term, dict):
        if term.get("t") == "i" or "i" in term:
            return str(term.get("i", ""))
        return str(term.get("v", ""))
    return "" if term is None else str(term)


def _wire_triples(lines: Iterable[str]) -> Iterator[tuple[str, str, str]]:
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            triple = json.loads(line)
        except json.JSONDecodeError as error:
            raise SystemExit(f"line {number}: not valid JSON ({error.msg})") from None
        yield (
            _wire_value(triple.get("s")),
            _wire_value(triple.get("p")),
            _wire_value(triple.get("o")),
        )


_URI_START = re.compile(r"^(urn:|https?://)\S*$")


def _text_triples(lines: Iterable[str]) -> Iterator[tuple[str, str, str]]:
    """Parse ``tg-show-graph`` output: ``subject predicate object`` per line.

    Subjects and predicates never contain spaces, so the object is the rest of the line. A
    line that does not start with a URI continues the previous multi-line literal.
    """
    pending: list[str] | None = None
    for line in lines:
        text = line.rstrip("\n")
        if text.startswith("Exception:"):
            raise SystemExit(f"tg-show-graph reported an error: {text}")
        parts = text.split(" ", 2)
        if len(parts) == 3 and _URI_START.match(parts[0]) and _URI_START.match(parts[1]):
            if pending is not None:
                yield pending[0], pending[1], pending[2]
            pending = parts
        elif pending is not None:
            pending[2] += "\n" + text
    if pending is not None:
        yield pending[0], pending[1], pending[2]


def read_triples(path: Path) -> list[tuple[str, str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    first = next((line for line in lines if line.strip()), "")
    parser = _wire_triples if first.lstrip().startswith("{") else _text_triples
    return list(parser(lines))


def build_entities(triples: Iterable[tuple[str, str, str]]) -> dict[str, Entity]:
    entities: dict[str, Entity] = {}
    for subject, predicate, obj in triples:
        entity = entities.setdefault(subject, Entity(subject))
        if predicate == RDF_TYPE:
            entity.types.add(obj)
        else:
            entity.props.setdefault(predicate, []).append(obj)
    return entities


# ------------------------------------------------------------------------------ conversion


def _session_id(uri: str) -> str | None:
    if not uri.startswith(AGENT_PREFIX):
        return None
    return uri[len(AGENT_PREFIX) :].split("/", 1)[0] or None


def _local_id(uri: str) -> str:
    """Turn an agent URI into a JourneyGraph identifier (letters, digits, ``.``, ``:``, ``-``)."""
    return re.sub(r"[^A-Za-z0-9._:-]", ".", uri[len(AGENT_PREFIX) :])[:128]


def _order_key(uri: str) -> tuple[int, int, int]:
    """Chronological position of an entity inside its own session."""
    suffix = uri[len(AGENT_PREFIX) :].partition("/")[2]
    if not suffix:
        return (0, 0, 0)
    if suffix == "pattern-decision":
        return (1, 0, 0)
    if suffix in ("decompose", "plan"):
        return (2, 0, 0)
    iteration = re.fullmatch(r"i(\d+)(/observation)?", suffix)
    if iteration:
        return (3, int(iteration.group(1)), 1 if iteration.group(2) else 0)
    indexed = re.fullmatch(r"(?:step|finding)/(\d+)", suffix)
    if indexed:
        return (4, int(indexed.group(1)), 0)
    return (5, 0, 0)  # final, synthesis


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _format_time(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


@dataclass
class Session:
    uri: str
    entity: Entity
    steps: list[Entity] = field(default_factory=list)
    parent: str | None = None  # URI of the Decomposition a sub-agent session derives from

    @property
    def is_root(self) -> bool:
        return self.parent is None


def group_sessions(entities: dict[str, Entity]) -> dict[str, Session]:
    sessions: dict[str, Session] = {}
    for uri, entity in entities.items():
        if (
            entity.is_a("AgentQuestion")
            and _session_id(uri)
            and "/" not in uri[len(AGENT_PREFIX) :]
        ):
            parent = entity.first(DERIVED_FROM)
            sessions[uri] = Session(uri, entity, parent=parent)
    for uri, entity in entities.items():
        if uri in sessions or entity.is_a("Thought"):
            continue
        session_id = _session_id(uri)
        owner = sessions.get(AGENT_PREFIX + session_id) if session_id else None
        if owner is not None:
            owner.steps.append(entity)
    for session in sessions.values():
        session.steps.sort(key=lambda step: _order_key(step.uri))
    return sessions


def _root_of(session: Session, sessions: dict[str, Session]) -> Session:
    seen = {session.uri}
    current = session
    while current.parent is not None:
        parent_session_id = _session_id(current.parent)
        parent = sessions.get(AGENT_PREFIX + parent_session_id) if parent_session_id else None
        if parent is None or parent.uri in seen:
            break
        seen.add(parent.uri)
        current = parent
    return current


def _describe(step: Entity, session: Session, entities: dict[str, Entity]) -> tuple[str, str]:
    """Return ``(operation_type, component)`` for one step entity."""
    if step.is_a("PatternDecision"):
        return "router", f"pattern:{step.first(TG + 'pattern') or 'unknown'}"
    if step.is_a("Analysis"):
        return "llm", "agent_llm"
    if step.is_a("Observation"):
        analysis = entities.get(step.uri.removesuffix("/observation"))
        action = analysis.first(TG + "action") if analysis else None
        return "tool", action or "unknown_tool"
    if step.is_a("Decomposition"):
        return "llm", "decomposer"
    if step.is_a("Plan"):
        return "llm", "planner"
    if step.is_a("StepResult"):
        return "agent", "plan_step"
    if step.is_a("Finding"):
        return "agent", "subagent_finding"
    if step.is_a("Conclusion") or step.is_a("Synthesis"):
        if not session.is_root:
            return "agent", "subagent_answer"
        reason = step.first(TG + "terminationReason")
        return "outcome", f"answer:{reason}" if reason else "answer"
    return "internal", "unknown_step"


def _outcome(step: Entity) -> str:
    reason = step.first(TG + "terminationReason")
    if reason is None:
        return "unknown"
    return "success" if reason in SUCCESS_REASONS else "failure"


def _session_events(
    session: Session,
    trace_id: str,
    start: datetime,
    entities: dict[str, Entity],
    metadata: dict[str, str],
    children_end: datetime | None,
) -> tuple[list[Record], datetime]:
    events: list[Record] = []
    cursor = start
    question_operation = ("request", "agent_question") if session.is_root else ("agent", "subagent")
    sequence: list[tuple[Entity, tuple[str, str]]] = [(session.entity, question_operation)]
    sequence += [(step, _describe(step, session, entities)) for step in session.steps]

    previous: datetime | None = None
    for entity, (operation_type, component) in sequence:
        if children_end is not None and (entity.is_a("Finding") or entity.is_a("Synthesis")):
            cursor = max(cursor, children_end)
        if previous is not None and cursor <= previous:
            # Zero-duration steps would share a timestamp, and JourneyGraph breaks such ties
            # by step_id. One microsecond keeps TrustGraph's own step order instead.
            cursor = previous + ORDERING_GAP
        previous = cursor
        duration = 0
        if entity.is_a("Analysis"):
            duration = entity.integer(TG + "llmDurationMs") or 0
        elif entity.is_a("Observation"):
            duration = entity.integer(TG + "toolDurationMs") or 0
        failed = entity.is_a("Error") or entity.first(TG + "toolError") is not None
        record: Record = {
            "schema_version": "1.0",
            "trace_id": trace_id,
            "step_id": _local_id(entity.uri),
            "timestamp": _format_time(cursor),
            "operation_type": operation_type,
            "component": component,
            "duration_ms": duration,
            "status": "error" if failed else "ok",
        }
        parent = entity.first(DERIVED_FROM)
        if entity.is_a("Observation") and not (parent and _session_id(parent)):
            # When a tool runs a GraphRAG or DocumentRAG query, TrustGraph derives the
            # Observation from that query's Synthesis rather than from the iteration.
            # Attach it to its own iteration so the trace stays connected.
            parent = entity.uri.removesuffix("/observation")
        if parent and (_session_id(parent) and parent in entities):
            record["parent_step_id"] = _local_id(parent)
        if operation_type == "outcome":
            record["outcome"] = _outcome(entity)
        for source, target in (("inToken", "input_tokens"), ("outToken", "output_tokens")):
            value = entity.integer(TG + source)
            if value is not None:
                record[target] = value
        event_metadata = dict(metadata)
        model = entity.first(TG + "llmModel")
        if model:
            event_metadata["model"] = model
        if event_metadata:
            record["metadata"] = event_metadata
        events.append(record)
        cursor += timedelta(milliseconds=duration)
    return events, cursor


def convert(
    entities: dict[str, Entity],
    version: str | None,
    only_roots: set[str] | None = None,
) -> tuple[list[Record], dict[str, int]]:
    sessions = group_sessions(entities)
    by_root: dict[str, list[Session]] = {}
    for session in sessions.values():
        root_uri = _root_of(session, sessions).uri
        if only_roots is None or root_uri in only_roots:
            by_root.setdefault(root_uri, []).append(session)

    events: list[Record] = []
    skipped = 0
    for root_uri in sorted(by_root):
        root = sessions[root_uri]
        root_start = _parse_time(root.entity.first(STARTED_AT))
        if root_start is None:
            skipped += 1
            continue
        trace_id = _local_id(root_uri)
        decision = next((s for s in root.steps if s.is_a("PatternDecision")), None)
        metadata: dict[str, str] = {}
        if decision is not None and decision.first(TG + "pattern"):
            metadata["workflow"] = str(decision.first(TG + "pattern"))
        if version:
            metadata["version"] = version

        children_end: datetime | None = None
        for child in sorted(by_root[root_uri], key=lambda s: s.uri):
            if child is root:
                continue
            child_start = _parse_time(child.entity.first(STARTED_AT)) or root_start
            child_events, child_end = _session_events(
                child, trace_id, child_start, entities, metadata, None
            )
            events.extend(child_events)
            children_end = child_end if children_end is None else max(children_end, child_end)
        root_events, _ = _session_events(
            root, trace_id, root_start, entities, metadata, children_end
        )
        events.extend(root_events)

    events.sort(key=lambda e: (str(e["trace_id"]), str(e["timestamp"]), str(e["step_id"])))
    stats = {
        "traces": len(by_root) - skipped,
        "sessions": sum(len(group) for group in by_root.values()),
        "events": len(events),
        "skipped_without_start_time": skipped,
    }
    return events, stats


def read_session_list(path: Path) -> set[str]:
    """Read top-level session URIs or bare session ids, one per line."""
    roots = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            roots.add(value if value.startswith(AGENT_PREFIX) else AGENT_PREFIX + value)
    return roots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("input", type=Path, help="wire-triple JSONL or tg-show-graph text")
    parser.add_argument("output", type=Path, help="JourneyGraph canonical JSONL to write")
    parser.add_argument("--version", help="label stored as metadata 'version' on every event")
    parser.add_argument(
        "--sessions",
        type=Path,
        help="file of top-level session URIs or ids, one per line; convert only those sessions",
    )
    args = parser.parse_args(argv)

    entities = build_entities(read_triples(args.input))
    only_roots = read_session_list(args.sessions) if args.sessions else None
    events, stats = convert(entities, args.version, only_roots)
    with args.output.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps(stats, sort_keys=True), file=sys.stderr)
    return 0 if events else 1


if __name__ == "__main__":
    raise SystemExit(main())
