# Privacy-Safe Real-Trace Discovery Protocol

This protocol advances [issue #5](https://github.com/GermanGerken/journeygraph/issues/5) by
defining how JourneyGraph can learn from legally usable, privacy-reviewed exports without
turning a public repository into a trace store. It is a procedure and evidence contract, not
evidence that any partner, source family, compatibility claim, or product priority has already
been validated.

## Working hypotheses

Until evidence from 2–3 design partners says otherwise, the working primary persona is:

> An AI or agent engineer who owns an agent workflow and can export traces locally.

The single target job hypothesis is:

> Given a privacy-reviewed batch export, identify recurring retries, loops, failures, or
> drop-offs and choose one concrete debugging target without uploading the traces.

Both statements have status `hypothesis`. A synthetic example, repository test, maintainer
opinion, or successful import cannot validate them. Change their status only by linking the
same structured run evidence used for every partner study.

## Non-negotiable boundary

- Raw or merely pseudonymized partner traces are private by default.
- Never attach a trace, generated report, command log, screenshot, or evidence bundle to a
  public issue or pull request before the publication gate passes.
- JourneyGraph filtering is key-based, not DLP or anonymization. Sanitize before JourneyGraph
  reads the export, then review every generated artifact again.
- Apache-2.0 for this repository does not grant a license to partner data.
- An ignored directory reduces accidental Git staging; it is not encryption, access control,
  consent, or a security boundary.
- A later successful retry does not replace or edit the original failed run record.

Public development continues to use deterministic synthetic fixtures. A real-derived fixture
requires separate written permission for that exact public use, aggressive minimization, and an
independent disclosure review; those conditions are stronger than permission for private
analysis or public aggregate findings.

## 1. Owner setup before recruitment

The repository owner must choose and document outside Git:

1. a private intake channel approved for the expected data classification;
2. encrypted private storage and backup policy;
3. named roles allowed to access raw, working, derived, and evidence files;
4. raw and derived retention periods plus deletion ownership;
5. a withdrawal process that can find and delete every retained copy;
6. an independent reviewer role for any proposed public summary or fixture.

Do not recruit or request an export until this setup exists. Public GitHub issues, PRs, Actions
artifacts, CI logs, chat transcripts, and unencrypted email attachments are not intake storage.

## 2. Partner and provenance gate

Before receiving each dataset, confirm all of the following in writing and retain only an opaque
reference in the evidence record:

- the authorizing person can permit use of the organization's export;
- the producer/exporter and exact upstream version are known, or the version is explicitly
  recorded as unknown with its attempted source;
- allowed uses are decided separately for private analysis, derived findings, public
  aggregates, and a public fixture;
- the permission or agreement covers the intended processing and access roles;
- raw and derived deletion dates and the withdrawal process are accepted;
- the data owner will minimize and sanitize the export before transfer;
- the source family is meaningfully distinct from the other study inputs.

The default allowed-use matrix is private analysis only. Silence never grants permission for a
public aggregate or fixture. Do not put a partner name, contract title, person, email, or raw
permission text into the evidence JSON; use an opaque reference resolvable only in the approved
private records system.

## 3. Private storage layout

Use one opaque dataset ID per export:

```text
data/private/real-trace-discovery/<dataset-id>/
├── source/          # received export; never opened by JourneyGraph
├── working/         # minimized and reviewed input
├── output/          # JourneyGraph artifacts and captured command result
└── evidence-log.json
```

`data/private/` is ignored by Git. Confirm the storage class and permissions before writing to
it. Do not use a partner or product name in `<dataset-id>`, filenames, aliases, or labels. Keep
permission documents, contact details, transformation keys, and ID mappings outside this tree
in the approved records system.

## 4. Sanitize before analysis

The data owner should minimize at export time. A permitted reviewer then performs and records a
second local pass before JourneyGraph runs:

1. Remove prompts, responses, messages, document bodies, embeddings, tool arguments/results,
   OTLP span-event payloads, span-link attributes/identifiers, status-message payloads, baggage,
   headers, cookies, authorization data, and all URLs or URIs by default. This does not mean
   deleting the normalized JourneyGraph event records needed for analysis; retain only their
   required structural fields. If route shape is demonstrably necessary for the target job,
   replace it before transfer with a documented generalized route category; never retain a
   hostname, literal path, query string, fragment, credential, or opaque resource identifier.
2. Remove people, user/session/customer/account identifiers, email, phone, IP, device, host,
   container, cloud-account, tenant, and deployment identifiers.
3. Replace trace/span/step identifiers with a consistent random mapping or keyed HMAC while
   preserving parent relationships and any required format length. Store neither the mapping
   nor HMAC key with the dataset.
4. Shift all timestamps by one private dataset-level offset, or bucket them when exact spacing
   is unnecessary. Preserve event order and durations required by the target job.
5. Generalize service, model, workflow, agent, component, environment, and region labels. Review
   rare labels and paths that could identify a partner or incident.
6. Retain only fields necessary for the stated job. Record dropped field categories, not raw
   field values.
7. Run an approved local secret/identifier scan and perform a separate manual review. Both must
   pass before JourneyGraph reads the working file.

The schema records the sanitization method and reviews. It intentionally does not store raw
values, transformation secrets, ID maps, local absolute paths, or scanner output. Repository
`make security` excludes ignored private files and is not evidence that a dataset was reviewed.

## 5. Standard run and evidence capture

Run from the approved private environment. Validate first, then analyze only accepted input:

```bash
journeygraph validate WORKING_INPUT --format INPUT_FORMAT
journeygraph analyze WORKING_INPUT --format INPUT_FORMAT --output-dir PRIVATE_OUTPUT
```

Do not copy the literal command line into the evidence JSON because it may expose paths. Record
the structured subcommand, input-format, dataset reference, and supported options instead.

Create a separate `runs[]` entry for every attempt, including failures. Record:

- JourneyGraph version and full commit SHA;
- exact producer/exporter version and how it was established on the dataset record;
- private input dimensions;
- result and CLI exit code;
- elapsed time and time to first usable result;
- warning codes/counts and failure codes without raw messages;
- manual transformations and dropped field categories from the schema's versioned vocabulary;
- maintainer intervention, minutes, and safe action summaries;
- referenced mapping gaps;
- whether the result was actionable, why, and the next step.

After every successful analysis, manually review stdout/stderr, `analysis.json`,
`normalized.jsonl`, `report.html`, and `graph.svg`. The event-level normalized file requires the
same protection as the input. If any artifact contains unsafe material, mark the artifact review
failed, stop sharing, and return to sanitization.

Use the strict [evidence schema](research/schemas/real-trace-evidence-v1.schema.json). The
[synthetic example](research/examples/real-trace-evidence.synthetic.json) demonstrates a failed
run followed by a successful retry; it is explicitly not product evidence.

## 6. Prioritized gap log

Each gap belongs to exactly one primary category:

- `ingestion`: the reader cannot decode or map the source shape;
- `canonical_model`: the source concept has no reviewed vendor-neutral representation;
- `analysis`: accepted canonical data cannot answer the target job;
- `documentation`: supported behavior exists but a user cannot apply it reliably.

Prioritize consistently:

- `p0`: disclosure/correctness risk or a blocker across all candidate inputs for the first
  compatibility slice;
- `p1`: blocks the target job or requires maintainer repair of partner data;
- `p2`: loses useful data but has an acceptable documented workaround;
- `p3`: documentation or usability friction that does not block a result.

A successful workaround does not erase the gap. Public issue URLs are optional and may be added
only after their title, body, logs, screenshots, dimensions, versions, and examples pass the
publication gate.

## 7. Publication gate

Private evidence stays under the `private_evidence` record class. To create a
`public_summary`, make a new minimized record rather than copying the private file. The schema
requires:

- bucketed, not exact private dimensions;
- no raw traces, direct identifiers, secrets, partner identity, local path, or private mapping;
- explicit permission for the exact publication;
- an opaque permission reference;
- a completed independent disclosure review with role and date.

Exact source versions can themselves identify a partner. Include them publicly only when the
permission and disclosure review cover that risk. A public fixture requires its own explicit
permission and review even when a public summary was approved.

## 8. Study completion and product decisions

Issue #5 can close only after the evidence log contains:

- 2–3 legally usable, privacy-reviewed exports from 2–3 partners;
- at least two source families;
- complete provenance, permissions, retention, access, and sanitization records;
- preserved successful and failed runs using this same schema;
- a prioritized gap log across all four categories;
- evidence-linked persona and target-job status;
- exact producer/exporter versions selected for the first `v0.2` compatibility slice.

Compatibility, persona, and scope decisions must cite run IDs. Do not count this protocol, the
synthetic example, repository tests, or an undocumented conversation toward those thresholds.

## Current evidence status

As of 2026-07-21, this repository records zero recruited partners, zero real exports, zero
exercised real source families, and no validated persona, job, or `v0.2` compatibility slice.
The next owner action is to establish the private channel/storage/reviewer setup, then recruit
2–3 design partners under the provenance gate.
