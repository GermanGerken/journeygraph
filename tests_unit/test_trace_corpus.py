from __future__ import annotations

import argparse
import copy
import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
trace_corpus = importlib.import_module("trace_corpus")


def _attribute(key: str, variant: str, value: object) -> dict[str, object]:
    return {"key": key, "value": {variant: value}}


def _span(
    *,
    trace_id: str = "a" * 32,
    span_id: str = "1" * 16,
    parent_id: str | None = None,
    name: str = "safe-operation",
    start: int = 100,
    end: int = 200,
    status: object = 0,
    attributes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "attributes": attributes or [],
        "status": {"code": status},
    }
    if parent_id is not None:
        value["parentSpanId"] = parent_id
    return value


def _payload(
    spans: list[dict[str, object]],
    *,
    service: str = "safe-service",
    scope: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attribute("service.name", "stringValue", service)]},
                "scopeSpans": [
                    {
                        "scope": scope or {"name": "safe.scope", "version": "1.0"},
                        "spans": spans,
                    }
                ],
            }
        ]
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _synthetic_provenance(fixture: Path, payload: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "fixture": trace_corpus._relative(fixture),
        "source": {
            "name": "JourneyGraph unit fixture",
            "repository": "https://github.com/GermanGerken/journeygraph",
            "version": "0.1.2 test contract",
            "commit": None,
        },
        "captured_on": "2026-08-07",
        "generation": ["unit test"],
        "source_license": {
            "spdx": "Apache-2.0",
            "url": "https://github.com/GermanGerken/journeygraph/blob/main/LICENSE",
        },
        "classification": "synthetic",
        "sanitization": {
            "tool": "scripts/trace_corpus.py",
            "version": "1.0",
            "actions": ["created without sensitive values"],
            "automated_checks": ["schema and digest validation"],
        },
        "limitations": ["unit-test evidence only"],
        "usage_limits": "Public synthetic unit-test fixture only.",
        "content_sha256": trace_corpus._sha256(fixture),
        "observed": trace_corpus._observed(payload),
    }


def test_committed_otlp_corpus_passes_structural_provenance_and_disclosure_checks() -> None:
    # Arrange
    args = argparse.Namespace()

    # Act
    result = trace_corpus.check(args)

    # Assert
    assert result == 0


@pytest.mark.parametrize(
    "unsafe",
    [
        {"prompt.body": "redacted"},
        {"response": "redacted"},
        {"document.contents": "redacted"},
        {"tool_parameters": "redacted"},
        {"http.headers": "redacted"},
        {"authorization": "redacted"},
        {"cookie": "redacted"},
        {"user.id": "redacted"},
        {"session.id": "redacted"},
        {"safe": "person@example.com"},
        {"safe": "+1 (202) 555-0100"},
        {"safe": "/Users/example/private/input.json"},
        {"safe": "Bearer abcdefghijklmnop"},
    ],
)
def test_disclosure_scan_rejects_sensitive_keys_and_content_patterns(unsafe: object) -> None:
    # Arrange, Act, Assert
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._scan_content(unsafe)


def test_disclosure_scan_allows_required_ids_and_semantic_counters() -> None:
    # Arrange
    safe = {
        "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "spanId": "1111111111111111",
        "attributes": [
            {"key": "llm.token_count.prompt", "value": {"intValue": "7"}},
            {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "3"}},
        ],
    }

    # Act
    trace_corpus._scan_content(safe)

    # Assert
    assert safe["traceId"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


@pytest.mark.parametrize(
    ("call", "value"),
    [
        (trace_corpus._object, []),
        (trace_corpus._list, {}),
        (trace_corpus._int, True),
        (trace_corpus._int, []),
        (trace_corpus._int, "not-an-integer"),
    ],
)
def test_boundary_helpers_reject_wrong_types(call: Any, value: object) -> None:
    # Arrange, Act, Assert
    with pytest.raises(trace_corpus.CorpusError):
        call(value, "test.location")


def test_boundary_helpers_accept_expected_types() -> None:
    # Arrange, Act
    object_value = trace_corpus._object({"safe": 1}, "object")
    list_value = trace_corpus._list([1], "list")
    integer_values = [trace_corpus._int("7", "int"), trace_corpus._int(8, "int")]

    # Assert
    assert object_value == {"safe": 1}
    assert list_value == [1]
    assert integer_values == [7, 8]


@pytest.mark.parametrize(
    ("wrapped", "expected"),
    [
        ({"stringValue": "safe"}, "safe"),
        ({"boolValue": True}, True),
        ({"intValue": "7"}, "7"),
        ({"doubleValue": 1.5}, 1.5),
        ({"bytesValue": "c2FmZQ=="}, "c2FmZQ=="),
        (
            {"arrayValue": {"values": [{"stringValue": "safe"}]}},
            {"values": [{"stringValue": "safe"}]},
        ),
        (
            {"kvlistValue": {"values": [_attribute("safe", "boolValue", True)]}},
            {"values": [_attribute("safe", "boolValue", True)]},
        ),
    ],
)
def test_any_value_decodes_every_supported_variant(
    wrapped: dict[str, object], expected: object
) -> None:
    # Arrange, Act
    decoded = trace_corpus._decode_any_value(wrapped, "value")

    # Assert
    assert decoded == expected


@pytest.mark.parametrize(
    "wrapped",
    [
        {},
        {"stringValue": "safe", "boolValue": True},
        {"stringValue": 1},
        {"boolValue": "true"},
        {"intValue": "no"},
        {"doubleValue": True},
        {"doubleValue": "1"},
        {"arrayValue": []},
        {"arrayValue": {"values": "not-an-array"}},
        {"kvlistValue": []},
        {"kvlistValue": {"values": "not-an-array"}},
        {"bytesValue": 7},
    ],
)
def test_any_value_rejects_invalid_variants(wrapped: dict[str, object]) -> None:
    # Arrange, Act, Assert
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._decode_any_value(wrapped, "value")


def test_attribute_map_decodes_values_and_rejects_bad_keys() -> None:
    # Arrange
    valid = [
        _attribute("safe", "stringValue", "value"),
        _attribute("count", "intValue", "3"),
    ]

    # Act
    decoded = trace_corpus._attribute_map(valid, "attributes")

    # Assert
    assert decoded == {"safe": "value", "count": "3"}
    for invalid in (
        [{"key": "", "value": {"stringValue": "safe"}}],
        [_attribute("same", "stringValue", "a"), _attribute("same", "stringValue", "b")],
    ):
        with pytest.raises(trace_corpus.CorpusError):
            trace_corpus._attribute_map(invalid, "attributes")


def test_request_reader_accepts_json_bom_and_collector_jsonl(tmp_path: Path) -> None:
    # Arrange
    payload = _payload([_span()])
    json_path = tmp_path / "request.json"
    json_path.write_text("\ufeff" + json.dumps(payload), encoding="utf-8")
    jsonl_path = tmp_path / "collector.jsonl"
    jsonl_path.write_text(f"{json.dumps(payload)}\n\n{json.dumps(payload)}\n", encoding="utf-8")

    # Act, Assert
    assert trace_corpus._requests(json_path) == [payload]
    assert trace_corpus._requests(jsonl_path) == [payload, payload]


@pytest.mark.parametrize("content", [b"", b"not-json\n", b"{}\nnot-json\n", b"\xff"])
def test_request_reader_rejects_empty_malformed_or_non_utf8_input(
    tmp_path: Path, content: bytes
) -> None:
    # Arrange
    input_path = tmp_path / "bad-input"
    input_path.write_bytes(content)

    # Act, Assert
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._requests(input_path)


def test_span_refs_expose_normalized_identity_time_parent_and_service() -> None:
    # Arrange
    payload = _payload(
        [
            _span(
                trace_id="A" * 32,
                span_id="B" * 16,
                parent_id="C" * 16,
                start=10,
                end=20,
            )
        ],
        service="catalog",
    )

    # Act
    ref = trace_corpus._span_refs([payload])[0]

    # Assert
    assert ref.trace_id == "a" * 32
    assert ref.span_id == "b" * 16
    assert ref.parent_id == "c" * 16
    assert (ref.start_ns, ref.end_ns, ref.service) == (10, 20, "catalog")
    assert trace_corpus.SpanRef(ref.span, {}, 0).service == "unknown-service"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("traceId", "short"),
        ("traceId", "0" * 32),
        ("spanId", "short"),
        ("spanId", "0" * 16),
        ("parentSpanId", "short"),
        ("parentSpanId", "0" * 16),
        ("name", " "),
        ("startTimeUnixNano", "-1"),
        ("endTimeUnixNano", "99"),
    ],
)
def test_span_refs_reject_invalid_identity_name_and_time(field: str, value: object) -> None:
    # Arrange
    span = _span(parent_id="2" * 16)
    span[field] = value

    # Act, Assert
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._span_refs([_payload([span])])


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("STATUS_CODE_UNSET", 0),
        ("STATUS_CODE_OK", 1),
        ("STATUS_CODE_ERROR", 2),
        ("2", 2),
    ],
)
def test_status_code_accepts_named_and_numeric_values(code: object, expected: int) -> None:
    # Arrange, Act
    actual = trace_corpus._status_code(_span(status=code))

    # Assert
    assert actual == expected


@pytest.mark.parametrize("code", ["STATUS_CODE_UNKNOWN", "3", -1])
def test_status_code_rejects_unknown_values(code: object) -> None:
    # Arrange, Act, Assert
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._status_code(_span(status=code))


def test_features_and_selection_cover_hierarchy_errors_order_and_concurrency() -> None:
    # Arrange
    parent = "9" * 16
    first = trace_corpus.SpanRef(
        _span(span_id="1" * 16, parent_id=parent, start=20, end=50, status=2),
        {"service.name": "one"},
        0,
    )
    second = trace_corpus.SpanRef(
        _span(span_id="2" * 16, parent_id=parent, start=30, end=40),
        {"service.name": "two"},
        1,
    )
    root = trace_corpus.SpanRef(_span(span_id=parent, start=10, end=60), {"service.name": "one"}, 2)

    # Act
    features = trace_corpus._features([first, second, root])
    selected = trace_corpus._select_trace_ids([first, second, root], 1)

    # Assert
    assert features == {
        "multi_service",
        "parent_child",
        "error",
        "out_of_order",
        "concurrent_siblings",
    }
    assert selected == {"a" * 32}
    assert trace_corpus._features([]) == set()
    assert trace_corpus._select_trace_ids([first], 0) == {"a" * 32}


def test_trace_selection_is_deterministic_when_not_every_trace_fits() -> None:
    # Arrange
    refs = [
        trace_corpus.SpanRef(_span(trace_id=trace, span_id=str(index + 1) * 16), {}, index)
        for index, trace in enumerate(("a" * 32, "b" * 32, "c" * 32))
    ]

    # Act
    selected = trace_corpus._select_trace_ids(refs, 2)

    # Assert
    assert selected == {"a" * 32, "b" * 32}


def test_safe_labels_and_nested_disclosure_scan_cover_allowed_provenance_links() -> None:
    # Arrange
    provenance = {
        "source": {"repository": "https://github.com/example/project"},
        "source_license": {"url": "https://github.com/example/project/blob/main/LICENSE"},
        "list": ["safe"],
    }

    # Act
    trace_corpus._scan_content(provenance, "provenance")

    # Assert
    assert trace_corpus._safe_label(" safe ", "label") == "safe"
    for invalid in (None, " ", "x" * 257):
        with pytest.raises(trace_corpus.CorpusError):
            trace_corpus._safe_label(invalid, "label")
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._scan_content({"url": "https://example.com"})


def test_attribute_sanitizer_keeps_only_allowlisted_safe_values() -> None:
    # Arrange
    raw = [
        _attribute("tool.name", "stringValue", "catalog"),
        _attribute("unknown", "stringValue", "discarded"),
        _attribute("llm.token_count.prompt", "intValue", "7"),
    ]

    # Act
    sanitized = trace_corpus._sanitize_attributes(
        raw, trace_corpus.SAFE_SPAN_ATTRIBUTES, "attributes"
    )

    # Assert
    assert [item["key"] for item in sanitized] == ["tool.name", "llm.token_count.prompt"]
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._sanitize_attributes(
            [_attribute("tool.name", "stringValue", "person@example.com")],
            trace_corpus.SAFE_SPAN_ATTRIBUTES,
            "attributes",
        )


def test_span_sanitizer_normalizes_enums_ids_and_offsets() -> None:
    # Arrange
    span = _span(
        trace_id="A" * 32,
        span_id="B" * 16,
        parent_id="C" * 16,
        start=10,
        end=20,
        status="STATUS_CODE_OK",
        attributes=[_attribute("tool.name", "stringValue", "catalog")],
    )
    span["kind"] = "SPAN_KIND_CLIENT"

    # Act
    sanitized = trace_corpus._sanitize_span(span, 5)

    # Assert
    assert sanitized["traceId"] == "a" * 32
    assert sanitized["spanId"] == "b" * 16
    assert sanitized["parentSpanId"] == "c" * 16
    assert sanitized["kind"] == 3
    assert sanitized["startTimeUnixNano"] == "15"
    assert sanitized["endTimeUnixNano"] == "25"
    assert sanitized["status"] == {"code": 1}
    invalid = _span()
    invalid["kind"] = 7
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._sanitize_span(invalid, 0)


def test_request_sanitizer_filters_unselected_traces_and_empty_containers() -> None:
    # Arrange
    selected = _span(trace_id="a" * 32, span_id="1" * 16, start=10, end=20)
    discarded = _span(trace_id="b" * 32, span_id="2" * 16, start=30, end=40)
    payload = _payload([selected, discarded])

    # Act
    sanitized = trace_corpus._sanitize_requests([payload], {"a" * 32})
    refs = trace_corpus._span_refs([sanitized])

    # Assert
    assert len(refs) == 1
    assert refs[0].trace_id == "a" * 32
    assert refs[0].start_ns == 1_767_225_600_000_000_000
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._sanitize_requests([payload], {"f" * 32})


def test_observed_dimensions_report_structure_relationships_and_outcomes() -> None:
    # Arrange
    parent = "9" * 16
    spans = [
        _span(span_id=parent, start=10, end=60),
        _span(
            span_id="1" * 16,
            parent_id=parent,
            start=20,
            end=50,
            status=2,
            attributes=[_attribute("journeygraph.outcome", "stringValue", "failure")],
        ),
        _span(span_id="2" * 16, parent_id="8" * 16, start=30, end=40),
    ]
    payload = _payload(spans)

    # Act
    observed = trace_corpus._observed(payload)

    # Assert
    assert observed == {
        "resource_spans": 1,
        "scope_spans": 1,
        "spans": 3,
        "traces": 1,
        "services": 1,
        "parent_links": 2,
        "missing_parent_links": 1,
        "error_spans": 1,
        "explicit_outcome_spans": 1,
        "traces_with_multi_service": 0,
        "traces_with_concurrent_siblings": 0,
        "traces_out_of_source_order": 0,
    }


def test_json_file_helpers_hash_write_and_bound_repository_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(trace_corpus, "REPOSITORY_ROOT", tmp_path)
    output = tmp_path / "test-data" / "fixtures" / "integration" / "sample.json"

    # Act
    trace_corpus._write_json(output, {"safe": "value"})

    # Assert
    assert trace_corpus._relative(output) == "test-data/fixtures/integration/sample.json"
    assert trace_corpus._sidecar(output).name == "sample.provenance.json"
    assert len(trace_corpus._sha256(output)) == 64
    assert json.loads(output.read_text(encoding="utf-8")) == {"safe": "value"}
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._relative(tmp_path.parent / "outside.json")


@pytest.mark.parametrize(
    ("field_path", "invalid"),
    [
        (("captured_on",), "not-a-date"),
        (("source", "version"), ""),
        (("source", "commit"), "not-a-commit"),
        (("source_license", "spdx"), "Not-A-License"),
        (("usage_limits",), 7),
        (("generation",), []),
        (("sanitization", "tool"), "other.py"),
        (("content_sha256",), "short"),
    ],
)
def test_provenance_schema_rejects_invalid_semantic_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_path: tuple[str, ...],
    invalid: object,
) -> None:
    # Arrange
    monkeypatch.setattr(trace_corpus, "REPOSITORY_ROOT", tmp_path)
    fixture = tmp_path / "test-data" / "fixtures" / "integration" / "sample.json"
    payload = _payload([_span()])
    _write_json(fixture, payload)
    provenance = _synthetic_provenance(fixture, payload)
    target: dict[str, object] = provenance
    for part in field_path[:-1]:
        target = target[part]  # type: ignore[assignment]
    target[field_path[-1]] = invalid

    # Act, Assert
    with pytest.raises(trace_corpus.CorpusError, match="schema violation"):
        trace_corpus._validate_provenance(provenance, fixture, payload)


def test_provenance_validation_rejects_path_digest_observation_and_unpinned_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(trace_corpus, "REPOSITORY_ROOT", tmp_path)
    fixture = tmp_path / "test-data" / "fixtures" / "integration" / "sample.json"
    payload = _payload([_span()])
    _write_json(fixture, payload)
    valid = _synthetic_provenance(fixture, payload)
    trace_corpus._validate_provenance(valid, fixture, payload)

    # Act, Assert
    mutations: list[dict[str, object]] = []
    wrong_path = copy.deepcopy(valid)
    wrong_path["fixture"] = "test-data/fixtures/integration/other.json"
    mutations.append(wrong_path)
    wrong_digest = copy.deepcopy(valid)
    wrong_digest["content_sha256"] = "f" * 64
    mutations.append(wrong_digest)
    wrong_observed = copy.deepcopy(valid)
    observed = dict(wrong_observed["observed"])  # type: ignore[arg-type]
    observed["spans"] = 2
    wrong_observed["observed"] = observed
    mutations.append(wrong_observed)
    for mutation in mutations:
        with pytest.raises(trace_corpus.CorpusError):
            trace_corpus._validate_provenance(mutation, fixture, payload)

    unpinned = copy.deepcopy(valid)
    unpinned["classification"] = "instrumented-demo"
    source = dict(unpinned["source"])  # type: ignore[arg-type]
    source.update(
        repository="https://github.com/example/unpinned",
        version="1.0.0",
        commit="a" * 40,
    )
    unpinned["source"] = source
    with pytest.raises(trace_corpus.CorpusError, match="not present in pin manifest"):
        trace_corpus._validate_provenance(unpinned, fixture, payload)


def test_json_schema_loader_rejects_invalid_schema_data_and_non_objects(
    tmp_path: Path,
) -> None:
    # Arrange
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("not-json", encoding="utf-8")
    array_json = tmp_path / "array.json"
    array_json.write_text("[]", encoding="utf-8")
    invalid_schema = tmp_path / "invalid-schema.json"
    invalid_schema.write_text('{"type": 7}', encoding="utf-8")
    strict_schema = tmp_path / "strict-schema.json"
    strict_schema.write_text(json.dumps({"type": "object", "required": ["safe"]}), encoding="utf-8")

    # Act, Assert
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._load_json_object(invalid_json, "invalid")
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._load_json_object(array_json, "array")
    with pytest.raises(trace_corpus.CorpusError, match="schema is invalid"):
        trace_corpus._validate_schema({}, invalid_schema, "document")
    with pytest.raises(trace_corpus.CorpusError, match="required"):
        trace_corpus._validate_schema({}, strict_schema, "document")


def test_requirements_lock_parser_is_strict_and_normalizes_names(tmp_path: Path) -> None:
    # Arrange
    valid = tmp_path / "valid.lock"
    valid.write_text("# comment\nPackage_Name==1.2.3\n", encoding="utf-8")

    # Act, Assert
    assert trace_corpus._requirements_pins(valid) == {"package-name": "1.2.3"}
    for content in ("", "package>=1\n", "same==1\nsame==2\n"):
        invalid = tmp_path / "invalid.lock"
        invalid.write_text(content, encoding="utf-8")
        with pytest.raises(trace_corpus.CorpusError):
            trace_corpus._requirements_pins(invalid)


def test_pin_manifest_drives_safe_compose_environment_and_consistency() -> None:
    # Arrange
    pins = trace_corpus._load_pins()

    # Act
    environment = trace_corpus._pin_environment(pins)
    trace_corpus._check_pin_consistency()

    # Assert
    assert environment["DEMO_VERSION"] == "3.0.0"
    assert environment["OTEL_DEMO_COMMIT"] == "1755859a9de82c2e5e225be68abc401a5ebf2b4f"
    assert environment["JOURNEYGRAPH_IMAGE_CHECKOUT"].endswith(
        "@sha256:3d18cb304a6af6a512c5e488bb19ee42be7d71bdf75a9786aa7296b8fb0a5036"
    )


def test_pin_environment_writer_allows_only_ignored_work_area(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setattr(trace_corpus, "REPOSITORY_ROOT", tmp_path)
    output = tmp_path / "test-data" / "work" / "pins.env"

    # Act
    result = trace_corpus.write_pin_env(argparse.Namespace(output=str(output)))

    # Assert
    assert result == 0
    assert "JOURNEYGRAPH_IMAGE_CHECKOUT=" in output.read_text(encoding="utf-8")
    for invalid in (tmp_path / "outside.env", tmp_path / "test-data" / "work" / "pins.txt"):
        with pytest.raises(trace_corpus.CorpusError):
            trace_corpus.write_pin_env(argparse.Namespace(output=str(invalid)))


def test_prepare_writes_sanitized_fixture_provenance_and_dimensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    monkeypatch.setattr(trace_corpus, "REPOSITORY_ROOT", tmp_path)
    raw = tmp_path / "raw.json"
    output = tmp_path / "test-data" / "fixtures" / "integration" / "prepared.json"
    template = tmp_path / "template.json"
    payload = _payload(
        [
            _span(
                attributes=[
                    _attribute("tool.name", "stringValue", "catalog"),
                    _attribute("http.url", "stringValue", "https://private.invalid"),
                ]
            )
        ]
    )
    _write_json(raw, payload)
    _write_json(output, payload)
    template_value = _synthetic_provenance(output, payload)
    for generated_field in ("fixture", "content_sha256", "observed"):
        template_value.pop(generated_field)
    _write_json(template, template_value)
    args = argparse.Namespace(
        input=str(raw),
        output=str(output),
        provenance_template=str(template),
        max_traces=0,
    )

    # Act
    result = trace_corpus.prepare(args)
    prepared = json.loads(output.read_text(encoding="utf-8"))
    provenance = json.loads(trace_corpus._sidecar(output).read_text(encoding="utf-8"))

    # Assert
    assert result == 0
    assert trace_corpus._observed(prepared)["spans"] == 1
    assert "http.url" not in json.dumps(prepared)
    assert provenance["content_sha256"] == trace_corpus._sha256(output)
    assert '"spans": 1' in capsys.readouterr().out


def test_fixture_discovery_filters_sidecars_and_check_requires_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    fixture_root = tmp_path / "fixtures"
    fixture = fixture_root / "sample.json"
    sidecar = fixture_root / "sample.provenance.json"
    _write_json(fixture, {})
    _write_json(sidecar, {})
    monkeypatch.setattr(trace_corpus, "EXPLICIT_FIXTURES", ())
    monkeypatch.setattr(trace_corpus, "FIXTURE_ROOTS", (fixture_root, tmp_path / "absent"))

    # Act, Assert
    assert trace_corpus._fixture_paths() == [fixture]
    monkeypatch.setattr(trace_corpus, "FIXTURE_ROOTS", (tmp_path / "absent",))
    with pytest.raises(trace_corpus.CorpusError, match="no OTLP fixtures"):
        trace_corpus.check(argparse.Namespace())


def test_check_rejects_missing_sidecar_without_running_external_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    fixture = tmp_path / "sample.json"
    _write_json(fixture, _payload([_span()]))
    monkeypatch.setattr(trace_corpus, "_fixture_paths", lambda: [fixture])
    monkeypatch.setattr(trace_corpus, "_check_pin_consistency", lambda: None)
    monkeypatch.setattr(trace_corpus, "_check_private_paths", lambda: None)

    # Act, Assert
    with pytest.raises(trace_corpus.CorpusError, match="missing provenance sidecar"):
        trace_corpus.check(argparse.Namespace())


def test_private_path_check_rejects_tracked_private_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    completed = subprocess.CompletedProcess(
        args=["git"], returncode=0, stdout=b"README.md\0data/private/trace.json\0", stderr=b""
    )
    monkeypatch.setattr(trace_corpus.subprocess, "run", lambda *args, **kwargs: completed)

    # Act, Assert
    with pytest.raises(trace_corpus.CorpusError, match="private"):
        trace_corpus._check_private_paths()


def test_inspect_parser_and_main_cover_each_cli_entrypoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    fixture = tmp_path / "fixture.json"
    _write_json(fixture, _payload([_span()]))
    parser = trace_corpus.build_parser()

    # Act
    inspect_args = parser.parse_args(["inspect", str(fixture)])
    prepare_args = parser.parse_args(
        [
            "prepare",
            "--input",
            "input.json",
            "--output",
            "output.json",
            "--provenance-template",
            "template.json",
        ]
    )
    check_args = parser.parse_args(["check"])
    pin_args = parser.parse_args(["write-pin-env", "--output", "pins.env"])
    result = trace_corpus.main(["inspect", str(fixture)])

    # Assert
    assert inspect_args.handler is trace_corpus.inspect_fixture
    assert prepare_args.handler is trace_corpus.prepare
    assert check_args.handler is trace_corpus.check
    assert pin_args.handler is trace_corpus.write_pin_env
    assert result == 0
    assert '"spans": 1' in capsys.readouterr().out

    monkeypatch.setattr(
        trace_corpus,
        "inspect_fixture",
        lambda _args: (_ for _ in ()).throw(trace_corpus.CorpusError("safe failure")),
    )
    failing_parser = trace_corpus.build_parser()
    monkeypatch.setattr(trace_corpus, "build_parser", lambda: failing_parser)
    assert trace_corpus.main(["inspect", str(fixture)]) == 1
    assert "trace corpus check failed: safe failure" in capsys.readouterr().err


def test_pin_consistency_detects_manifest_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    pins = trace_corpus._load_pins()
    drifted = copy.deepcopy(pins)
    collector = dict(drifted["collector"])  # type: ignore[arg-type]
    collector["image"] = "example.invalid/collector:1.0@sha256:" + "a" * 64
    drifted["collector"] = collector
    manifest = tmp_path / "pins.json"
    _write_json(manifest, drifted)
    monkeypatch.setattr(trace_corpus, "PIN_MANIFEST_PATH", manifest)

    # Act, Assert
    with pytest.raises(trace_corpus.CorpusError, match="collector image differs"):
        trace_corpus._check_pin_consistency()


def test_pin_consistency_rejects_missing_upstream_demo_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    for source in (
        "test-data/pins.json",
        "test-data/schemas/pins-v1.schema.json",
        "test-data/openinference/requirements.lock",
        "test-data/collector/compose.yaml",
        "test-data/collector/demo-override.yaml",
        "test-data/openinference/capture.sh",
        "test-data/openinference/provenance-template.json",
        "test-data/opentelemetry-demo/provenance-template.json",
    ):
        destination = tmp_path / source
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / source).read_bytes())
    demo_capture = tmp_path / "test-data/opentelemetry-demo/capture.sh"
    demo_capture.parent.mkdir(parents=True, exist_ok=True)
    demo_capture.write_text("write-pin-env\n", encoding="utf-8")
    monkeypatch.setattr(trace_corpus, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(trace_corpus, "PIN_MANIFEST_PATH", tmp_path / "test-data/pins.json")
    monkeypatch.setattr(
        trace_corpus,
        "PIN_SCHEMA_PATH",
        tmp_path / "test-data/schemas/pins-v1.schema.json",
    )

    # Act, Assert
    with pytest.raises(trace_corpus.CorpusError, match="upstream environment"):
        trace_corpus._check_pin_consistency()


def test_pin_environment_rejects_unsafe_values() -> None:
    # Arrange
    pins = trace_corpus._load_pins()
    unsafe = copy.deepcopy(pins)
    demo = dict(unsafe["otel_demo"])  # type: ignore[arg-type]
    images = dict(demo["images"])  # type: ignore[arg-type]
    images["checkout"] = "unsafe value"
    demo["images"] = images
    unsafe["otel_demo"] = demo

    # Act, Assert
    with pytest.raises(trace_corpus.CorpusError, match="unsafe environment"):
        trace_corpus._pin_environment(unsafe)


def test_instrumented_source_pin_accepts_exact_openinference_record() -> None:
    # Arrange
    provenance = trace_corpus._load_json_object(
        ROOT / "test-data/openinference/provenance-template.json", "template"
    )

    # Act
    trace_corpus._validate_instrumented_source(
        provenance, "openinference.provenance.json", trace_corpus._load_pins()
    )

    # Assert
    source = provenance["source"]
    assert isinstance(source, dict)
    assert source["commit"] == "a374cbdcec6bf712a005549d15293c57c27cd109"

    unpinned_license = copy.deepcopy(provenance)
    license_record = dict(unpinned_license["source_license"])  # type: ignore[arg-type]
    license_record["url"] = "https://github.com/Arize-ai/openinference/blob/main/LICENSE"
    unpinned_license["source_license"] = license_record
    with pytest.raises(trace_corpus.CorpusError, match="license URL is not pinned"):
        trace_corpus._validate_instrumented_source(
            unpinned_license,
            "openinference.provenance.json",
            trace_corpus._load_pins(),
        )
