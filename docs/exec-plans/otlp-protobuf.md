# OTLP Protobuf Input ExecPlan

This short living plan completes the protocol item of Stage 4: read binary OTLP protobuf
trace data, the native encoding of OTLP/HTTP and of the OpenTelemetry Collector file exporter
with `format: proto`, through the existing OTLP mapping.

Status: **implemented on `feat/stage4-complete`; awaiting review.** The owner asked on
2026-11-08 to complete Stage 4 before preparing 0.3.0, which this plan records as approval.

## Sources (checked 2026-11-08)

- [OTLP specification 1.11.1](https://opentelemetry.io/docs/specs/otlp/): an OTLP/HTTP binary
  body is one Protobuf-encoded `ExportTraceServiceRequest`; OTLP/JSON differs by hex-encoded
  `traceId`/`spanId`, integer enums, and decimal-string 64-bit integers.
- [Collector file exporter README](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/a07387b98e8c/exporter/fileexporter/README.md):
  with `format: proto` and no compression, the file holds length-prefixed messages: "each
  encoded message is preceded by 4 bytes (a big-endian unsigned 32 bit integer)". zstd adds
  per-message or stream compression.
- [opentelemetry-proto v1.10.0](https://github.com/open-telemetry/opentelemetry-proto/tree/v1.10.0)
  `trace.proto`, `common.proto`, `resource.proto`, `trace_service.proto` for field numbers.
  `TracesData` and `ExportTraceServiceRequest` both carry `repeated ResourceSpans` as field 1.

## Contract decisions

- Two explicit formats, never auto-detected: `otlp-proto` (one binary request body, for
  example an OTLP/HTTP capture) and `otlp-proto-file` (Collector file exporter `format: proto`,
  uncompressed, length-prefixed). Compressed files are rejected with a fix hint.
- A standard-library protobuf wire decoder reads exactly the fields the OTLP/JSON importer
  uses (resource attributes, scope spans, span IDs, parent, name, kind, start and end times,
  attributes, status) and produces the same request structure as OTLP/JSON (hex IDs, integer
  enums, decimal-string 64-bit integers, `AnyValue` wrappers). Unknown fields are skipped per
  the wire format. No runtime dependency is added; the analytical core stays stdlib-only.
- Malformed input (truncated varints or fields, wrong wire types for known fields, lengths
  beyond the buffer, nesting deeper than the OTLP schema allows) is a format error
  `malformed_otlp_proto` with a byte offset, never an internal error. Each length-prefixed
  message is bounded by the remaining file size.
- The `otlp_chronological_adjacency` warning applies as for the other OTLP formats.

## Test oracle

`opentelemetry-proto` (Apache-2.0) and `protobuf` (BSD-3-Clause) are added to the `dev`
extra only. Tests encode the committed OTLP/JSON corpora with the official library and assert
that `otlp-proto` and `otlp-proto-file` produce analysis payloads and normalized events equal
to `otlp-json`. Hand-written byte strings cover malformed and unknown-field cases.

## Non-goals

gRPC, live receivers, zstd or gzip decompression, metrics and logs, and the profiles string
table (`string_value_strindex`, `key_strindex`).

## Progress

- [x] 2026-11-08: Read the sources above; implemented the decoder, both formats, tests with
  the official encoder as oracle, and documentation.

## Decision log

- **Decoder in the standard library.** The needed schema subset is small and fixed by the
  pinned proto version; a dependency-free decoder keeps the core installable without extras.
  The official library is used where it is strongest: as an independent test oracle.
- **Two formats, not one with sniffing.** A bare request and a length-prefixed file cannot be
  distinguished reliably from their first bytes.

## Outcomes and retrospective

Verification on macOS with Python 3.12 on 2026-11-08: `make verify` passed with 648 tests (14
intentionally skipped) and 96.81% combined coverage. All four committed OTLP/JSON corpora,
encoded with the official library as one request and as a length-prefixed per-span file,
produce analysis payloads and normalized events equal to `otlp-json`. `make mutation`:
`otlp_proto.py` 684 of 851 killed (80.4%); most survivors change error-message text or
skip-branches for fields the importer ignores.

Discoveries: the first mutation run failed to collect tests because the unit and integration
suites both had a `test_otlp_proto.py` module; the unit module is now
`test_otlp_proto_decoder.py`. Synthetic hexadecimal IDs in tests carry an inline
`pragma: allowlist secret`.
