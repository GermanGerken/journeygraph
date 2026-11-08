# Collector JSON Lines Input ExecPlan

This short living plan implements the first item of Stage 4 of the product roadmap: let users
analyze OpenTelemetry Collector file-exporter output without a conversion script.

Status: **implemented and merged in #29.** Approved by the owner on 2026-11-08 as part of the
product roadmap.

## Purpose and observable outcome

The Collector file exporter writes one JSON-encoded `ExportTraceServiceRequest` per line.
Before this plan, JourneyGraph accepted only a single request body (`--format otlp-json`), and
the repository's own harness needed `scripts/trace_corpus.py` to merge lines. Now
`--format otlp-jsonl` reads such files directly with the same span mapping, so analysis of a
split export equals analysis of the merged request.

## Contract decisions

- New explicit format `otlp-jsonl`; it is never auto-detected, because `.jsonl` already means
  canonical events.
- Each non-empty line must be one request object; blank lines are ignored; a file without any
  request line is a format error (`empty_otlp_jsonl`). Invalid JSON is `malformed_otlp_jsonl`
  with the line and column. Structural errors reuse existing OTLP codes with a `line N.` prefix.
- The `otlp_chronological_adjacency` warning applies as for `otlp-json`.
- No gzip, protobuf file format, rotation handling, or receiver.

## Evidence and tests

- Integration: the three committed OTLP fixtures (OpenInference scenarios, OpenTelemetry Demo
  3.0.0, golden edge cases) are re-encoded one span per line; the analysis payload (excluding
  location-bearing warnings) and normalized events equal the single-request results.
- Integration: malformed, empty, non-object, and structurally invalid lines.
- Functional: installed CLI on a committed synthetic two-line fixture derived from
  `otlp_trace.json`, and a malformed-line error with exit code 2.

No claim is made about raw Collector captures beyond this re-encoding evidence; the harness's
raw output remains uncommitted by policy.

## Progress

- [x] 2026-11-08: Implemented reader, format wiring, tests, and documentation.

## Outcomes and retrospective

Verification on macOS with Python 3.12 on 2026-11-08: `make verify` passed with 412 tests
(10 skipped: rejected fixtures in the schema sweep and one non-canonical fixture) and 95.75%
combined branch-aware coverage. The new fixture's synthetic hexadecimal trace ID was added to
`.secrets.baseline` with the same hash as the already-allowed `otlp_trace.json`.
