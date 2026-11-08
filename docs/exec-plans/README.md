# Execution Plans

Significant features and architectural changes in JourneyGraph are developed from self-contained
execution plans.

Current plans:

- [`journeygraph-mvp.md`](journeygraph-mvp.md) records the implemented v0.1 architecture,
  contracts, validation strategy, and release evidence.
- [`real-trace-discovery.md`](real-trace-discovery.md) prepares the privacy-safe evidence process
  for issue #5 without claiming that any partner or real export has been validated.
- [`pypi-trusted-publishing.md`](pypi-trusted-publishing.md) records the secretless,
  exact-artifact publication and verification of `v0.1.1` for issue #4.
- [`semantic-safety.md`](semantic-safety.md) corrects missing-outcome inference and makes the
  chronological-only OTLP analysis boundary visible before real-trace compatibility work.
- [`instrumented-trace-harness.md`](instrumented-trace-harness.md) builds a reproducible,
  privacy-gated corpus from official OpenTelemetry and OpenInference instrumentation without
  widening the product importer or requiring a hosted observability service.
- [`readable-report.md`](readable-report.md) adds per-node and per-transition
  statistics, ranked association-only findings, and a layered, outcome-colored graph layout
  under analysis schema 1.1.
- [`path-variants.md`](path-variants.md) adds explainable path variants, recurring sequences
  with sequence-association findings, and trace filters under analysis schema 1.2.
- [`diff-and-check.md`](diff-and-check.md) adds `journeygraph diff` and `journeygraph check`
  for release comparisons and journey-level CI rules.
- [`collector-jsonl.md`](collector-jsonl.md) adds the experimental `otlp-jsonl` input for
  OpenTelemetry Collector file-exporter output.
- [`field-mapping.md`](field-mapping.md) adds experimental declarative TOML field mappings
  (`--mapping`) for JSON Lines, CSV, and Parquet exports of any shape.
- [`inspect-command.md`](inspect-command.md) adds `journeygraph inspect`, which describes an
  export without printing values and drafts a field mapping for review.
- [`vendor-presets.md`](vendor-presets.md) adds experimental packaged mappings for the
  documented Langfuse observations and Arize Phoenix span export shapes.
