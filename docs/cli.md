# CLI and Python API

JourneyGraph 0.1 provides three commands: `validate`, `analyze`, and `demo`. Every command
operates on local files. There is no stdin, URL, collector, server, account, or network input
mode.

## Installation

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

Optional Parquet decoding requires:

```bash
python -m pip install '.[parquet]'
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

Auto-detection is extension-based. `.json` is intentionally ambiguous and is not inferred as
OTLP. See [Data and Analysis Schemas](schema.md) for exact contracts and upstream OTLP sources.

## Validate

```text
journeygraph validate INPUT
    [--format auto|jsonl|csv|parquet|otlp-json]
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

## Analyze

```text
journeygraph analyze INPUT --output-dir DIR
    [--format auto|jsonl|csv|parquet|otlp-json]
    [--allow-metadata-key KEY ...]
    [--cohort-key KEY]
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

## Exit codes and streams

| Code | Meaning |
| --- | --- |
| `0` | Success, including success with data-quality or privacy warnings. |
| `1` | Unexpected internal failure, interrupt, or broken output stream. |
| `2` | CLI usage, selected-format, decode, or canonical validation error. |
| `3` | Input/output filesystem failure. |
| `4` | Unsafe path, overwrite refusal, or input/output collision. |

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
- missing explicit outcomes inferred as failure or drop-off;
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
from journeygraph.api import analyze_file, validate_file, write_analysis

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
