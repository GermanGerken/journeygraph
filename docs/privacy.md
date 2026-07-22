# Privacy and Threat Model

JourneyGraph analyzes local files and writes local artifacts. Its product path does not call
an LLM, require an API key or account, start a server, send telemetry, or make a network
request. It does not collect traces from running applications.

Local processing reduces data movement; it does not make trace data anonymous or harmless.
Users remain responsible for the files they provide, the output location they select, and
any report they share.

## Data used by the canonical model

JourneyGraph needs operational data to construct journeys:

- trace and step identifiers;
- an optional parent-step identifier;
- timestamps;
- operation types and component labels;
- duration and status;
- optional outcomes;
- optional input/output token and cost values;
- explicitly retained operational metadata.

Raw prompts, responses, messages, document bodies, tool arguments, credentials, and personal
identifiers are not required for graph analysis.

## Metadata policy

Metadata is denied by default except for a small operational allowlist:

```text
agent, cohort, environment, model, region, service, version, workflow
```

`--allow-metadata-key KEY` can add another operational key. Key comparison is case-insensitive
and normalizes non-alphanumeric runs to underscores. Retained output uses that normalized key.
If multiple source spellings normalize to the same allowed key, JourneyGraph excludes that key
entirely and emits a safe ordinal warning instead of selecting one source value.

Additional allowlisting cannot override the permanent sensitive-key policy. A key is excluded
when its normalized form contains one of these fragments:

```text
account_id, address, api_key, apikey, authorization, bearer, body, choice,
cookie, credit_card, customer_id, document, email, embedding, employee_id,
first_name, full_name, input_value, last_name, message, output_value, password,
passwd, personal, phone, prompt, refresh_token, response, secret, session_id,
ssn, token, tool_argument, user_id, username, visitor_id
```

This is deliberately conservative and applies after key normalization. For example, spelling,
case, punctuation, or an explicit `--allow-metadata-key` option cannot make `API-Key`,
`user.email`, or `PromptText` retainable.

Retained metadata values must be scalar strings, integers, finite floats, booleans, or null.
Nested mappings and arrays, non-finite numbers, invalid Unicode/XML text, and strings longer
than 512 characters are excluded. Non-string keys are excluded. Each exclusion produces a safe
warning with an ordinal field location. Rejected raw keys and values are not echoed because a
field name can itself contain sensitive or terminal-control content.

Unknown top-level event fields are also excluded with warnings. They are not automatically
treated as metadata.

## What filtering does not guarantee

Filtering is key-based. It is not content inspection, pseudonymization, anonymization, or a
data-loss-prevention system. An allowed value can still contain sensitive content. In
particular, these may remain identifying or confidential:

- `trace_id`, `step_id`, and parent IDs;
- component and operation labels;
- precise timestamps;
- agent, model, service, region, environment, workflow, and version values;
- cohort names;
- rare paths, small groups, durations, token counts, and costs.

Do not put prompts, responses, user names, customer IDs, secrets, or document content into an
allowlisted field or operational label. Inspect generated artifacts before sharing them.

## Generated artifacts

`journeygraph analyze` writes four fixed-name artifacts:

- `analysis.json` — aggregate analytics and retained labels/metadata;
- `normalized.jsonl` — every accepted canonical event after filtering;
- `report.html` — a static human-readable report with embedded aggregate JSON;
- `graph.svg` — a standalone graph with labels and counts.

The normalized file is event-level data, not only aggregates. Treat it at least as carefully
as the source export. The HTML and SVG can expose uncommon labels and paths even when metadata
was filtered.

The HTML renderer contextually escapes untrusted text, embeds JSON in a non-executable data
block, uses no JavaScript or remote resource, and includes a restrictive Content Security
Policy. The SVG renderer escapes XML and emits no script, event handler, foreign object, or
remote link. These controls prevent supported values from becoming executable markup; they do
not make the values non-sensitive.

## Filesystem controls and limitations

JourneyGraph rejects an explicit output path containing `..`, an output root that is itself a
symbolic link, and a collision or existing-file alias with the input file, including
case-insensitive aliases. It refuses to replace an existing output file or write into a
non-empty analysis directory unless `--force` is supplied.

Files are rendered before publication and written through temporary siblings followed by
atomic replacement where supported. Publication of the complete multi-file set is not a
filesystem transaction. An I/O failure can leave a subset of complete artifacts. Inspect and
remove incomplete output directories before retrying.

`--force` authorizes replacement of JourneyGraph's fixed artifact names; it does not sanitize
the directory or make a shared location private.

## Threats considered

### Sensitive-data propagation

Controls: a short allowlist, permanent key denylist, scalar-only values, safe warnings, and
downstream leakage tests.

Residual risk: sensitive content can be placed in an allowed value, identifier, or label.

### HTML and SVG injection

Controls: contextual escaping, static markup, a non-executable JSON block, Content Security
Policy, no JavaScript, and parser-based adversarial tests.

Residual risk: generated files still contain user-controlled text and should be opened only
with normal local-file precautions.

### Accidental overwrite or path confusion

Controls: explicit input/output paths, fixed artifact names, traversal and direct-symlink-root
checks, input collision checks, opt-in force, and per-file atomic replacement.

Residual risk: parent directories can have platform-specific behavior; force replaces files;
the multi-file output is not transactional.

### Resource exhaustion

Controls: bounded identifier and label lengths, explicit format errors, and deterministic
algorithms intended for local analytical workloads.

Residual risk: version 0.1 does not claim resistance to hostile files designed to exhaust
memory, CPU, or disk. Readers and normalization materialize substantial input in memory.

### Dependency and toolchain compromise

Controls: a standard-library runtime core, optional PyArrow isolated to Parquet ingestion,
bounded development dependencies, dependency auditing, static analysis, and secret scanning.

Residual risk: installing optional or development dependencies expands the supply-chain
surface. Review dependency changes and use a trusted package index.

## Design-partner traces and discovery evidence

Real-export product discovery has a stricter boundary than ordinary synthetic development.
Permission for private analysis does not authorize a public aggregate, fixture, report,
screenshot, log, or issue. The repository license does not grant rights to partner data.

Before JourneyGraph reads a partner export, the data owner must minimize it and an authorized
reviewer must remove or transform sensitive content, direct and operational identifiers, exact
timestamps, identifying labels, rare categories, URLs, headers, and infrastructure details. A
consistent ID mapping may preserve relationships, but pseudonymization is not anonymization.
Review every generated artifact again because `normalized.jsonl`, allowed values, labels, exact
dimensions, warnings, and uncommon paths can remain identifying.

Raw, working, output, and evidence files stay in approved encrypted private storage under an
explicit access and retention policy. `data/private/` is the repository-local convention and is
ignored by Git, but ignore rules are not access control or proof of sanitization. Repository
secret scanning does not inspect ignored private datasets.

A public summary must be created as a separate minimized record with bucketed dimensions,
explicit permission for that publication, and an independent disclosure review. A real-derived
fixture needs its own explicit public-fixture permission and review. Follow the complete
[Privacy-Safe Real-Trace Discovery Protocol](real-trace-discovery.md) and its validated evidence
schema; never use a public issue or pull request as the intake channel.

## Safe operating practices

1. Export only the operational fields required for the question being analyzed.
2. Remove sensitive content at the source before JourneyGraph reads the file.
3. Use restrictive filesystem permissions and a private output directory.
4. Avoid cohort reports for groups so small that individual traces can be inferred.
5. Inspect `normalized.jsonl`, labels, warnings, HTML, and SVG before sharing.
6. Delete local source and output files according to your retention policy.
7. Do not attach real traces or secrets to public issues or pull requests.

For vulnerability reporting, follow [Security Policy](../SECURITY.md).
