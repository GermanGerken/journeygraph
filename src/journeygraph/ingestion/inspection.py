"""Advisory inspection of non-canonical exports and draft field-mapping generation.

Inspection describes a sample of source records by path, type, and shape, and proposes a draft
TOML mapping.  It never reports source values unless the caller explicitly asks for short
identifier-like tokens of enumeration fields.  Suggestions are deterministic heuristics; the
draft keeps unfilled required fields as ``TODO`` comments so it cannot validate by accident.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from journeygraph.domain.models import SourceRecord
from journeygraph.ingestion.mapping import MappingError, parse_mapping
from journeygraph.normalization.privacy import DEFAULT_METADATA_ALLOWLIST

DEFAULT_SAMPLE = 1_000
MAX_DISTINCT_TRACKED = 101
MAX_SHOWN_VALUES = 20
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$")
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
# (lower bound inclusive, upper bound exclusive, unit) for epoch values.
_EPOCH_RANGES = (
    (Decimal("1e8"), Decimal("1e11"), "unix_s"),
    (Decimal("1e11"), Decimal("1e14"), "unix_ms"),
    (Decimal("1e14"), Decimal("1e17"), "unix_us"),
    (Decimal("1e17"), Decimal("1e20"), "unix_ns"),
)
_DURATION_SUFFIXES = {
    "ms": "ms",
    "millis": "ms",
    "milliseconds": "ms",
    "s": "s",
    "sec": "s",
    "secs": "s",
    "seconds": "s",
    "us": "us",
    "micros": "us",
    "microseconds": "us",
    "ns": "ns",
    "nanos": "ns",
    "nanoseconds": "ns",
}
_KNOWN_OPERATION_TYPES = frozenset(
    {
        "agent",
        "chain",
        "client",
        "consumer",
        "embedding",
        "evaluator",
        "guardrail",
        "handoff",
        "internal",
        "llm",
        "model",
        "outcome",
        "producer",
        "prompt",
        "request",
        "reranker",
        "retrieval",
        "retriever",
        "router",
        "server",
        "span",
        "tool",
        "unspecified",
        "validation",
    }
)
_METADATA_ALIASES = {"env": "environment", "region": "region", "svc": "service"}
_REQUIRED = ("trace_id", "step_id", "timestamp", "operation_type", "component", "status")
_TRACE_WORDS = frozenset({"trace", "session", "conversation", "thread", "run"})
_STEP_WORDS = frozenset({"span", "step", "event", "observation", "node", "call"})
_START_WORDS = frozenset({"start", "started", "timestamp", "time", "ts", "created", "begin"})
_END_WORDS = frozenset({"end", "ended", "finish", "finished", "stop", "completed"})


@dataclass(slots=True)
class _Collector:
    present: int = 0
    nulls: int = 0
    types: set[str] = field(default_factory=set)
    strings_all_identifier: bool = True
    strings_all_rfc3339: bool = True
    numeric_all: bool = True
    epoch_units: set[str] = field(default_factory=set)
    hashes: set[str] = field(default_factory=set)
    tokens: dict[str, None] = field(default_factory=dict)
    tokens_complete: bool = True


@dataclass(frozen=True, slots=True)
class FieldProfile:
    """What inspection observed for one source leaf path; never a source value."""

    segments: tuple[str, ...]
    path: str | None
    present: int
    nulls: int
    types: tuple[str, ...]
    hints: tuple[str, ...]
    distinct: str
    epoch_unit: str | None
    tokens: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A proposed source path for one mapping entry and the reason for it."""

    target: str
    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class Inspection:
    """A complete advisory inspection of a record sample."""

    sampled: int
    total: int
    profiles: tuple[FieldProfile, ...]
    fields: Mapping[str, Suggestion]
    timestamp_unit: str
    duration: Mapping[str, str]
    metadata: Mapping[str, Suggestion]
    show_values: bool


def _leaves(
    value: object, prefix: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], object]]:
    if isinstance(value, Mapping) and (value or not prefix):
        for key, child in value.items():
            yield from _leaves(child, (*prefix, str(key)))
    else:
        yield prefix, value


def render_path(segments: Sequence[str]) -> str | None:
    """Render segments in mapping-path syntax, or ``None`` when a segment needs a quote."""

    parts: list[str] = []
    for segment in segments:
        if '"' in segment:
            return None
        parts.append(f'"{segment}"' if "." in segment or not segment else segment)
    return ".".join(parts)


def _kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return type(value).__name__


def _number(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, float):
            parsed = Decimal(repr(value))
        elif isinstance(value, int):
            parsed = Decimal(value)
        elif isinstance(value, str) and value.strip():
            parsed = Decimal(value.strip())
        else:
            return None
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _epoch_unit(number: Decimal) -> str | None:
    for low, high, unit in _EPOCH_RANGES:
        if low <= number < high:
            return unit
    return None


def _observe(collector: _Collector, value: object, keep_tokens: bool) -> None:
    collector.present += 1
    kind = _kind(value)
    if kind == "null":
        collector.nulls += 1
        return
    collector.types.add(kind)
    digest = hashlib.sha256(repr((kind, value)).encode("utf-8", "surrogatepass")).hexdigest()
    if len(collector.hashes) < MAX_DISTINCT_TRACKED:
        collector.hashes.add(digest)
    if isinstance(value, str):
        collector.strings_all_identifier &= bool(_IDENTIFIER.fullmatch(value))
        collector.strings_all_rfc3339 &= bool(_RFC3339.fullmatch(value))
        if keep_tokens:
            if _TOKEN.fullmatch(value) and len(collector.tokens) <= MAX_SHOWN_VALUES:
                collector.tokens.setdefault(value, None)
            else:
                collector.tokens_complete = False
    else:
        collector.strings_all_identifier = collector.strings_all_rfc3339 = False
    number = _number(value)
    if number is None:
        collector.numeric_all = False
        return
    unit = _epoch_unit(number)
    collector.epoch_units.add(unit or "none")


def _bucket(count: int) -> str:
    if count <= 1:
        return "1"
    if count <= 10:
        return "2-10"
    if count <= 100:
        return "11-100"
    return ">100"


def _profile(segments: tuple[str, ...], collector: _Collector, keep_tokens: bool) -> FieldProfile:
    observed = collector.present - collector.nulls
    hints: list[str] = []
    epoch_unit = None
    if observed:
        if collector.types == {"string"} and collector.strings_all_rfc3339:
            hints.append("rfc3339")
        elif collector.types == {"string"} and collector.strings_all_identifier:
            hints.append("identifier")
        if collector.numeric_all:
            hints.append("numeric")
            if len(collector.epoch_units) == 1 and "none" not in collector.epoch_units:
                epoch_unit = next(iter(collector.epoch_units))
                hints.append(f"epoch_{epoch_unit.removeprefix('unix_')}")
        if collector.types == {"object"}:
            hints.append("empty_object")
    tokens = None
    if (
        keep_tokens
        and collector.tokens_complete
        and collector.tokens
        and len(collector.tokens) <= MAX_SHOWN_VALUES
    ):
        tokens = tuple(sorted(collector.tokens))
    distinct = len(collector.hashes)
    return FieldProfile(
        segments=segments,
        path=render_path(segments),
        present=collector.present,
        nulls=collector.nulls,
        types=tuple(sorted(collector.types)) or ("null",),
        hints=tuple(hints),
        distinct="0"
        if not distinct
        else (">100" if distinct >= MAX_DISTINCT_TRACKED else _bucket(distinct)),
        epoch_unit=epoch_unit,
        tokens=tokens,
    )


def _words(segments: Sequence[str]) -> list[str]:
    words: list[str] = []
    for segment in segments:
        words.extend(match.lower() for match in _WORD.findall(segment))
    return words


def _is_text(profile: FieldProfile) -> bool:
    return profile.types == ("string",)


def _is_instant(profile: FieldProfile) -> bool:
    return "rfc3339" in profile.hints or profile.epoch_unit is not None


def _few(profile: FieldProfile) -> bool:
    return profile.distinct in {"1", "2-10", "11-100"}


def _candidates(profile: FieldProfile) -> dict[str, int]:
    """Score every target this path could fill; higher is better, absent means unsuitable."""

    words = _words(profile.segments)
    if not words or profile.path is None:
        return {}
    word_set = set(words)
    last = words[-1]
    has_id = last in {"id", "uuid", "key"} or "id" in word_set
    identifier = "identifier" in profile.hints or profile.types in {("integer",), ("string",)}
    scores: dict[str, int] = {}
    if "parent" in word_set and has_id and identifier:
        scores["parent_step_id"] = 4
    elif has_id and identifier:
        if word_set & _TRACE_WORDS:
            scores["trace_id"] = 3 + (last in {"id", "uuid"})
        elif word_set & _STEP_WORDS or words == ["id"]:
            scores["step_id"] = 3 + (last in {"id", "uuid"})
    if _is_instant(profile):
        if word_set & _END_WORDS:
            scores["end"] = 3
        elif word_set & _START_WORDS or {"at"} & word_set:
            scores["timestamp"] = 3 + bool(word_set & {"start", "started", "timestamp"})
    if "numeric" in profile.hints and not _is_instant(profile):
        if word_set & {"duration", "latency", "elapsed"}:
            scores["duration"] = 3
        if word_set & {"cost", "price", "usd"}:
            scores["cost_usd"] = 3
        if "tokens" in word_set or "token" in word_set:
            if word_set & {"prompt", "input"}:
                scores["input_tokens"] = 3
            elif word_set & {"completion", "output"}:
                scores["output_tokens"] = 3
    if _is_text(profile) and not has_id:
        if word_set & {"kind", "type", "operation", "category"} and _few(profile):
            scores["operation_type"] = 3
        if word_set & {"outcome", "result", "verdict"} and _few(profile):
            scores["outcome"] = 3
        if word_set & {"tool", "component", "function", "operation"} and last in {
            "name",
            "tool",
            "component",
            "function",
        }:
            scores["component"] = 3 + (last == "name")
        elif last == "name" and not word_set & {"prompt", "user", "first", "last", "full"}:
            scores["component"] = 2
    enumerable = _is_text(profile) or profile.types == ("integer",)
    if enumerable and not has_id and word_set & {"status", "state"} and _few(profile):
        scores["status"] = 3
    return scores


_TARGET_ORDER = (
    "trace_id",
    "parent_step_id",
    "step_id",
    "timestamp",
    "end",
    "duration",
    "operation_type",
    "component",
    "status",
    "outcome",
    "input_tokens",
    "output_tokens",
    "cost_usd",
)


def _assign(profiles: Sequence[FieldProfile]) -> dict[str, tuple[FieldProfile, int]]:
    scored = [(profile, _candidates(profile)) for profile in profiles]
    chosen: dict[str, tuple[FieldProfile, int]] = {}
    used: set[str] = set()
    for target in _TARGET_ORDER:
        options = [
            (score[target], profile)
            for profile, score in scored
            if target in score and profile.path is not None and profile.path not in used
        ]
        if not options:
            continue
        options.sort(key=lambda item: (-item[0], len(item[1].segments), str(item[1].path)))
        best_score, best = options[0]
        chosen[target] = (best, best_score)
        used.add(str(best.path))
    return chosen


def _metadata(profiles: Sequence[FieldProfile], used: set[str]) -> dict[str, Suggestion]:
    suggestions: dict[str, Suggestion] = {}
    for profile in sorted(profiles, key=lambda item: (len(item.segments), str(item.path))):
        if profile.path is None or profile.path in used or not profile.segments:
            continue
        if not _is_text(profile) and profile.types not in {("integer",), ("number",), ("boolean",)}:
            continue
        last = profile.segments[-1].lower()
        key = _METADATA_ALIASES.get(last, last)
        if key in DEFAULT_METADATA_ALLOWLIST and key not in suggestions:
            suggestions[key] = Suggestion(key, profile.path, "allowlisted name")
    return suggestions


def inspect_records(
    records: Sequence[SourceRecord], *, sample: int = DEFAULT_SAMPLE, show_values: bool = False
) -> Inspection:
    """Profile the first ``sample`` records and propose mapping entries."""

    if isinstance(sample, bool) or not isinstance(sample, int) or sample < 1:
        raise ValueError("sample must be a positive integer")
    sampled = records[:sample]
    collectors: dict[tuple[str, ...], _Collector] = {}
    for record in sampled:
        for segments, value in _leaves(record.data):
            if segments:
                _observe(collectors.setdefault(segments, _Collector()), value, show_values)
    profiles = tuple(
        _profile(segments, collectors[segments], show_values) for segments in sorted(collectors)
    )
    chosen = _assign(profiles)
    fields: dict[str, Suggestion] = {}
    duration: dict[str, str] = {}
    timestamp_unit = "iso8601"
    for target, (profile, score) in chosen.items():
        reason = "name+shape" if score >= 3 else "name"
        path = str(profile.path)
        if target == "timestamp":
            timestamp_unit = profile.epoch_unit or "iso8601"
            fields[target] = Suggestion(target, path, reason)
        elif target in {"end", "duration"}:
            continue
        else:
            fields[target] = Suggestion(target, path, reason)
    timestamp = chosen.get("timestamp")
    end = chosen.get("end")
    if timestamp is not None and end is not None and end[0].epoch_unit == timestamp[0].epoch_unit:
        duration = {"start": str(timestamp[0].path), "end": str(end[0].path)}
    elif "duration" in chosen:
        profile = chosen["duration"][0]
        suffix = _words(profile.segments)[-1]
        duration = {"field": str(profile.path), "unit": _DURATION_SUFFIXES.get(suffix, "ms")}
    used = {suggestion.path for suggestion in fields.values()} | set(duration.values())
    return Inspection(
        sampled=len(sampled),
        total=len(records),
        profiles=profiles,
        fields=fields,
        timestamp_unit=timestamp_unit,
        duration=duration,
        metadata=_metadata(profiles, used),
        show_values=show_values,
    )


def _value_map(target: str, tokens: Sequence[str]) -> list[str]:
    lines: list[str] = []
    for token in tokens:
        lowered = token.lower()
        mapped: str | None = None
        if target == "status":
            if "error" in lowered or "fail" in lowered:
                mapped = "error"
            elif "unset" in lowered:
                mapped = "unset"
            elif lowered.endswith("ok") or "success" in lowered:
                mapped = "ok"
        elif target == "outcome":
            for outcome in ("success", "failure", "handoff", "dropoff", "unknown"):
                if lowered == outcome:
                    mapped = outcome
            if mapped is None and ("fail" in lowered or "error" in lowered):
                mapped = "failure"
        elif lowered in _KNOWN_OPERATION_TYPES:
            mapped = lowered
        key = json.dumps(token)
        if mapped is None:
            lines.append(f'# {key} = ""  # TODO: choose a canonical value')
        elif mapped != token:
            lines.append(f"{key} = {json.dumps(mapped)}")
    return lines


def render_draft(inspection: Inspection) -> str:
    """Return a commented TOML draft; unfilled required fields stay as TODO comments."""

    profiles = {profile.path: profile for profile in inspection.profiles}
    lines = [
        "# Draft field mapping generated by `journeygraph inspect` from "
        f"{inspection.sampled} sampled record(s).",
        "# Every entry is a heuristic suggestion: review each line before using this file.",
        'mapping_version = "1"',
        "",
        "[fields]",
    ]
    for target in (
        *_REQUIRED,
        "parent_step_id",
        "outcome",
        "input_tokens",
        "output_tokens",
        "cost_usd",
    ):
        suggestion = inspection.fields.get(target)
        if suggestion is not None:
            lines.append(f"{target} = {json.dumps(suggestion.path)}  # {suggestion.reason}")
        elif target in _REQUIRED:
            lines.append(f'# {target} = ""  # TODO: required; no candidate path was found')
    if not inspection.duration:
        lines.append(
            '# duration_ms = ""  # TODO: required; map a duration field or a [duration] pair'
        )
    if inspection.timestamp_unit != "iso8601":
        lines += ["", "[timestamp]", f"unit = {json.dumps(inspection.timestamp_unit)}"]
    if inspection.duration:
        lines += ["", "[duration]"]
        lines += [f"{key} = {json.dumps(value)}" for key, value in inspection.duration.items()]
    for target in ("status", "outcome", "operation_type"):
        suggestion = inspection.fields.get(target)
        if suggestion is None:
            continue
        profile = profiles.get(suggestion.path)
        tokens = profile.tokens if profile is not None else None
        if inspection.show_values and tokens:
            entries = _value_map(target, tokens)
            if entries:
                lines += ["", f"[values.{target}]", *entries]
        elif not inspection.show_values:
            lines += [
                "",
                f"# [values.{target}]  # map source values to canonical {target} values if needed;",
                "# rerun with --show-values to list short observed tokens.",
            ]
    if inspection.metadata:
        lines += ["", "[metadata]"]
        lines += [
            f"{key} = {json.dumps(suggestion.path)}  # {suggestion.reason}"
            for key, suggestion in sorted(inspection.metadata.items())
        ]
    draft = "\n".join(lines) + "\n"
    complete = all(target in inspection.fields for target in _REQUIRED) and inspection.duration
    if complete:
        try:
            parse_mapping(draft)
        except MappingError as error:  # pragma: no cover - would be a rendering defect
            raise AssertionError(f"generated draft does not parse: {error}") from error
    return draft


def render_report(inspection: Inspection) -> str:
    """Return a plain-text, value-free description of the sample and the suggestions."""

    suggested = {suggestion.path: name for name, suggestion in inspection.fields.items()}
    for key, value in inspection.duration.items():
        if key in {"start", "end", "field"}:
            suggested.setdefault(value, f"duration {key}")
    for key, suggestion in inspection.metadata.items():
        suggested.setdefault(suggestion.path, f"metadata {key}")
    header = ("path", "present", "null", "types", "hints", "distinct", "suggestion")
    rows = [
        (
            profile.path or "(unaddressable: key contains a quote)",
            str(profile.present),
            str(profile.nulls),
            ",".join(profile.types),
            ",".join(profile.hints) or "-",
            profile.distinct,
            suggested.get(profile.path, "-") if profile.path else "-",
        )
        for profile in inspection.profiles
    ]
    widths = [max(len(row[index]) for row in (header, *rows)) for index in range(len(header))]
    lines = [
        f"inspected: {inspection.sampled} of {inspection.total} record(s); "
        f"{len(inspection.profiles)} source path(s)",
        "  ".join(cell.ljust(width) for cell, width in zip(header, widths, strict=True)).rstrip(),
    ]
    lines += [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    ]
    missing = [target for target in _REQUIRED if target not in inspection.fields]
    if not inspection.duration:
        missing.append("duration_ms")
    lines.append("missing required fields: " + (", ".join(missing) if missing else "none"))
    if inspection.show_values:
        by_path = {profile.path: profile for profile in inspection.profiles}
        for target in ("status", "outcome", "operation_type"):
            chosen = inspection.fields.get(target)
            profile = by_path.get(chosen.path) if chosen is not None else None
            if profile is not None and profile.tokens:
                lines.append(f"observed {target} tokens: {', '.join(profile.tokens)}")
    return "\n".join(lines) + "\n"
