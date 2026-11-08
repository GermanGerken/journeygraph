# CLI and Python API

JourneyGraph 0.1 provides three commands: `validate`, `analyze`, and `demo`. Every command
operates on local files. There is no stdin, URL, collector, server, account, or network input
mode.

## Installation

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install journeygraph
```

Optional Parquet decoding requires:

```bash
python -m pip install 'journeygraph[parquet]'
```

Repository contributors should use `make setup`, which creates the editable development
environment and installs the pinned quality tools described in [Testing and Quality](testing.md).

The installed version is available with:

```bash
journeygraph --version
```

## Format selection and maturity

| Format | Selection | Maturity and boundary |
| --- | --- | --- |
| JSON Lines | `--format jsonl` or `.jsonl`/`.ndjson` auto-detection | Stable canonical input; one event object per line. |
| CSV | `--format csv` or `.csv` auto-detection | Stable canonical scalar input; `metadata.<key>` columns. |
| Parquet | `--format parquet` or `.parquet`/`.pq` auto-detection | Optional canonical input through PyArrow; not installed by default. |
| OTLP/JSON | explicit `--format otlp-json` only | Experimental importer for one uncompressed official OTLP/HTTP JSON trace request shape. |
| OTLP JSON Lines | explicit `--format otlp-jsonl` only | Experimental importer for Collector file-exporter output: one request object per non-empty line, same mapping as OTLP/JSON. |
| OTLP protobuf | explicit `--format otlp-proto` only | Experimental importer for one binary `ExportTraceServiceRequest` (an OTLP/HTTP protobuf body), same mapping. |
| OTLP protobuf file | explicit `--format otlp-proto-file` only | Experimental importer for Collector file-exporter `format: proto` output: uncompressed, 4-byte big-endian length-prefixed messages. |

Auto-detection is extension-based. `.json` is intentionally ambiguous and is not inferred as
OTLP. See [Data and Analysis Schemas](schema.md) for exact contracts and upstream OTLP sources.

### Field mappings

`--mapping FILE` (on `validate`, `analyze`, `diff`, and `check`) reads JSON Lines, CSV, or
Parquet records in any shape and builds canonical events from a declarative TOML mapping
before validation:

```bash
journeygraph validate export.jsonl --mapping mapping.toml --normalized-out events.jsonl
journeygraph analyze export.jsonl --mapping mapping.toml --output-dir report
```

With a mapping, CSV and Parquet need no canonical column names, and `metadata.*` CSV columns
are ordinary columns. `validate --normalized-out` writes the mapped canonical events, which is
the recommended way to check a new mapping. A mapping cannot be combined with OTLP formats
(usage error, exit code `2`); an invalid mapping document is a usage error and an unreadable
mapping file an I/O error (exit code `3`). Source values that cannot be mapped are validation
errors that name the record location and the source path, never the value. The document
format is specified in [Field mappings](schema.md#field-mappings).

### Presets

`--preset NAME` (mutually exclusive with `--mapping`) applies a packaged, experimental
mapping for a documented vendor export shape:

| Preset | Input |
| --- | --- |
| `langfuse-observations` | Langfuse enriched observations export (`observations_v2/`) as JSON Lines. |
| `langsmith-runs` | LangSmith run objects from `runs.query` / `POST /api/v2/runs/query`, one per line. |
| `phoenix-spans` | Arize Phoenix span objects in the REST API shape, one per line. |

```bash
journeygraph analyze observations.jsonl --preset langfuse-observations --output-dir report
journeygraph presets
journeygraph presets --show phoenix-spans > my-mapping.toml
```

`journeygraph presets` lists each preset with its source documentation and the date it was
checked; `--show NAME` prints its TOML to copy and adapt into a `--mapping` file. Presets
follow vendor documentation only and were not tested against real exports; see
[Vendor presets](schema.md#vendor-presets). An unknown preset name, or `--preset` with
`--mapping` or an OTLP format, is a usage error (exit code `2`).

## Validate

```text
journeygraph validate INPUT
    [--format auto|jsonl|csv|parquet|otlp-json|otlp-jsonl|otlp-proto|otlp-proto-file]
    [--mapping FILE | --preset NAME]
    [--allow-metadata-key KEY ...]
    [--normalized-out PATH]
    [--force]
```

Example:

```bash
journeygraph validate traces.jsonl \
  --normalized-out accepted.jsonl
```

Validation decodes, validates, orders, deduplicates, reconciles outcomes, and filters metadata.
It prints accepted event/trace/warning counts. Without `--normalized-out`, it writes no file.

`--allow-metadata-key` is repeatable and extends the operational allowlist. It cannot override
the sensitive-key denylist. The normalized file follows the same privacy policy.

An existing normalized output is not replaced unless `--force` is supplied. The output may
not collide with the input file.

## Inspect

```text
journeygraph inspect INPUT
    [--format auto|jsonl|csv|parquet]
    [--sample N]
    [--mapping-out PATH]
    [--show-values]
    [--force]
```

Example:

```bash
journeygraph inspect export.jsonl --mapping-out mapping.toml
journeygraph validate export.jsonl --mapping mapping.toml --normalized-out events.jsonl
```

`inspect` profiles the first `N` records (default `1000`) of a JSON Lines, CSV, or Parquet
file in any shape. It prints one line per source leaf path with the number of records that
contain it, how many are null, the observed types, shape hints (`identifier`, `rfc3339`,
`numeric`, `epoch_s`, `epoch_ms`, `epoch_us`, `epoch_ns`, `empty_object`), a bucketed
distinct-value count (`1`, `2-10`, `11-100`, `>100`), and the canonical field it suggests. It
then lists required fields it could not fill. It prints no source value.

`--mapping-out` writes a commented draft [field mapping](schema.md#field-mappings). Every
entry is a deterministic heuristic based on path names and value shapes, and required fields
without a candidate stay as `# ... TODO` lines, so an incomplete draft fails `validate` until
it is finished. Review every line before use. The draft is not replaced without `--force` and
cannot overwrite the input.

`--show-values` is an explicit opt-in. For the paths suggested as `status`, `outcome`, and
`operation_type` only, it lists up to 20 distinct observed tokens made of letters, digits,
`_`, `.`, `:`, and `-` (at most 64 characters) and drafts `[values.*]` tables from them.
Tokens it cannot classify are left as `TODO` comments. Free text never qualifies.

Inspection is advisory: incomplete suggestions do not fail the command. Invalid options and
unreadable input are exit code `2`, I/O errors `3`, and an output conflict `4`.

## Analyze

```text
journeygraph analyze INPUT --output-dir DIR
    [--format auto|jsonl|csv|parquet|otlp-json|otlp-jsonl|otlp-proto|otlp-proto-file]
    [--mapping FILE | --preset NAME]
    [--allow-metadata-key KEY ...]
    [--cohort-key KEY]
    [--min-support N]
    [--outcome OUTCOMES ...]
    [--since TIMESTAMP]
    [--until TIMESTAMP]
    [--force]
```

Example:

```bash
journeygraph analyze traces.jsonl \
  --output-dir journeygraph-report \
  --cohort-key environment
```

The cohort key defaults to `cohort`. Analysis automatically allows the selected cohort key,
subject to the permanent sensitive-key policy. A trace with no retained value appears in the
missing cohort; a trace with multiple values is assigned its first chronological value and is
included in the conflict count.

`--min-support N` sets the minimum number of traces or events behind a ranked key finding
(default `3`). It must be a positive integer; any other value is a usage error with exit code
`2`. The value is recorded in `analysis.json` under `findings.config.min_support`. It also
sets the minimum number of traces for a published recurring sequence.

Trace filters apply after validation and before analysis:

- `--outcome success,failure` (comma-separated or repeated) keeps traces whose reconciled
  outcome is listed; allowed values are `success`, `failure`, `handoff`, `dropoff`, `unknown`.
- `--since` and `--until` take ISO 8601 timestamps with an explicit offset or `Z`. A trace is
  kept when its first event is at or after `since` and strictly before `until`.

Invalid values are usage errors (exit code `2`). Filters that keep no trace, or a window whose
`since` is not before `until`, are validation errors (exit code `2`); no artifacts are written.
`normalized.jsonl` contains only the retained traces, and `analysis.json` records the filters
and trace counts under `filters`.

On success the directory contains:

| File | Contents |
| --- | --- |
| `analysis.json` | Versioned deterministic graph and analytics payload. |
| `normalized.jsonl` | Privacy-filtered canonical events. |
| `report.html` | Static escaped local report; no executable JavaScript or remote dependency. |
| `graph.svg` | Standalone escaped aggregate graph. |

The target must be empty unless `--force` is supplied. Force allows JourneyGraph to replace
its fixed artifact names in a non-empty directory; unrelated files are not removed.

## Demo

```text
journeygraph demo [--output-dir DIR] [--force]
```

Example:

```bash
journeygraph demo --output-dir journeygraph-demo
```

The demo uses packaged deterministic synthetic AI-agent events. It writes the four standard
artifacts plus `demo-traces.jsonl`. It needs no network, account, API key, or model.

The default output directory is `journeygraph-demo`. As with analysis, a non-empty directory
requires `--force`.

## Diff

```text
journeygraph diff BASELINE CANDIDATE --output-dir DIR
    [--format auto|jsonl|csv|parquet|otlp-json|otlp-jsonl|otlp-proto|otlp-proto-file]
    [--mapping FILE | --preset NAME]
    [--allow-metadata-key KEY ...]
    [--cohort-key KEY]
    [--min-support N]
    [--outcome OUTCOMES ...] [--since TIMESTAMP] [--until TIMESTAMP]
    [--force]
```

Example:

```bash
journeygraph diff last-week.jsonl this-week.jsonl --output-dir release-diff
```

Both inputs are analyzed with identical options, then compared. The command writes
`diff.json` (`diff_schema_version: "1.0"`) and a static, escaped `diff.html`, and prints each
notable change. The comparison covers outcome rates, success among known outcomes with a 95%
Newcombe interval for the difference, categories (added, removed, common; trace share, error
rate, p95 duration, success), transitions, path variants, and mean cost, tokens, and duration.

Notable changes (at most 15) are emitted when success among known outcomes moves by at least 5
percentage points, a category appears or disappears in at least `--min-support` traces, a
category's trace share or error-event rate moves by at least 10 points, a path variant's share
moves by at least 10 points, or mean cost per trace or event p95 duration changes by at least
20%. They describe differences between two samples, not their causes.

## Check

```text
journeygraph check INPUT --rules RULES.toml
    [--baseline BASELINE]
    [--summary-md PATH]
    [analysis options as for analyze]
    [--force]
```

Example rules:

```toml
[thresholds]
min_success_rate = 0.8          # success among known outcomes
max_failure_rate = 0.1          # failure among known outcomes
max_unknown_rate = 0.5          # unknown outcomes among traces
max_error_event_rate = 0.05     # error events among events
max_mean_cost_per_trace = 0.05  # supplied cost; fails when no cost is present
max_p95_duration_ms = 5000      # global event p95

[regressions]                    # requires --baseline
max_success_rate_drop = 0.05
max_error_event_rate_increase = 0.02
max_mean_cost_per_trace_increase = 0.25   # relative
forbid_new_categories = true
```

The command prints `PASS` or `FAIL` per rule and a total, and exits `5` when any rule fails. A
rule whose observation is unavailable (for example, no cost values) fails explicitly. The
relative cost regression passes when cost is zero on both sides and fails when only the
baseline is zero.
`--summary-md` writes a Markdown table, for example to `$GITHUB_STEP_SUMMARY`; an existing
file is replaced only with `--force`. Unknown tables or rules, wrong types, and regression
rules without `--baseline` are usage errors (exit code `2`).

## Exit codes and streams

| Code | Meaning |
| --- | --- |
| `0` | Success, including success with data-quality or privacy warnings. |
| `1` | Unexpected internal failure, interrupt, or broken output stream. |
| `2` | CLI usage, selected-format, decode, or canonical validation error. |
| `3` | Input/output filesystem failure. |
| `4` | Unsafe path, overwrite refusal, or input/output collision. |
| `5` | `check` evaluated the rules and at least one failed. |

Stable success information and warnings are printed to stdout. Actionable errors are printed
to stderr. Ordinary user-input failures do not emit Python tracebacks.

## Output-path behavior

JourneyGraph rejects:

- an explicit output path containing a `..` component;
- an output root that is itself a symbolic link;
- a normalized output that resolves or aliases to the input file, including a
  case-insensitive filesystem alias;
- an analysis artifact that resolves or aliases to the input file;
- an existing output file without `--force`;
- a non-empty analysis directory without `--force`;
- an output-directory path that exists but is not a directory.

Each file is written through a temporary sibling and replaced atomically where supported.
The complete multi-file directory is not transactional; see [Privacy and Threat Model](privacy.md).

## Warnings and errors

Warnings do not block output. Common warnings include:

- input rows reordered chronologically;
- equal timestamps ordered by `step_id`;
- exact duplicate events removed;
- missing explicit business outcomes classified as `unknown`;
- OTLP paths and transitions limited to chronological adjacency rather than parent-aware
  control flow;
- missing, cross-trace, or time-inconsistent parents;
- disconnected parent structures;
- unknown valid operation types;
- excluded unknown, nested, oversized, non-finite, or sensitive metadata;
- high-cardinality operation/component categories.

Blocking errors include missing required fields, malformed identifiers or timestamps, invalid
status/outcome/schema values, negative or non-finite metrics, conflicting duplicate identities,
parent cycles, malformed format structure, and empty input.

Issue messages contain a code, safe location, explanation, and corrective hint. They are
designed not to echo input values.

## Python API

The supported composition surface is:

```python
from journeygraph.api import analyze_file, compare_files, validate_file, write_analysis

dataset = validate_file("traces.jsonl", input_format="jsonl")
analysis = analyze_file(
    "traces.jsonl",
    input_format="jsonl",
    cohort_key="cohort",
)
artifacts = write_analysis(analysis, "journeygraph-report")
```

### `validate_file`

```python
validate_file(
    input_path,
    *,
    input_format="auto",
    allow_metadata_keys=(),
) -> NormalizedDataset
```

Returns immutable accepted events, grouped traces, warnings, the selected input format, and
the original record count. It does not write output.

### `analyze_file`

```python
analyze_file(
    input_path,
    *,
    input_format="auto",
    cohort_key="cohort",
    allow_metadata_keys=(),
) -> Analysis
```

Returns an `Analysis` containing the normalized dataset, deterministic report mapping, and
resolved input path. Resolving the path at analysis time preserves input/artifact collision
protection if the process later changes its working directory. Passing `cohort_key=None` through
the Python API disables cohort grouping.

### `write_analysis`

```python
write_analysis(
    analysis,
    output_dir,
    *,
    force=False,
    extra_files=None,
) -> AnalysisArtifacts
```

Publishes the standard artifact set. `extra_files`, when used by an integration, accepts only
plain unique filenames and cannot replace a standard artifact name.

The functions and `Analysis` dataclass exported by `journeygraph.api`, with the signatures
shown above, are the documented composition surface for version 0.1. Other module import
paths, exception classes, dataclass constructors, and underscore-prefixed functions are not
currently a compatibility promise.

## Interpretation limits

Path/outcome and cohort/outcome differences are associations. JourneyGraph does not perform
causal inference, clustering, prediction, quality judging, or prompt optimization. Missing
telemetry remains missing; cost values are summarized as supplied and are not recalculated
from provider pricing.
