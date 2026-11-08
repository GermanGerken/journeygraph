"""Binary OTLP protobuf decodes to the same records as OTLP/JSON.

The official ``opentelemetry-proto`` encoder is the independent oracle: each committed OTLP/JSON
corpus is encoded with it, and the standard-library decoder must reproduce the JSON results.
"""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path
from typing import Any

import pytest

from journeygraph.api import analyze_file, validate_file
from journeygraph.exceptions import FormatError

trace_service_pb2 = pytest.importorskip("opentelemetry.proto.collector.trace.v1.trace_service_pb2")
json_format = pytest.importorskip("google.protobuf.json_format")

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    ROOT / "test-data" / "fixtures" / "integration" / "openinference-scenarios.otlp.json",
    ROOT / "test-data" / "fixtures" / "integration" / "otel-demo-3.0.0.otlp.json",
    ROOT / "tests_integration" / "fixtures" / "otlp" / "golden" / "edge-cases.otlp.json",
    ROOT / "tests_functional" / "fixtures" / "otlp_trace.json",
]
_ID_KEYS = {"traceId", "spanId", "parentSpanId"}


def _hex_ids_to_base64(value: Any) -> Any:
    """Convert OTLP/JSON hex identifiers to the base64 the standard protobuf JSON parser expects."""

    if isinstance(value, dict):
        return {
            key: base64.b64encode(bytes.fromhex(item)).decode("ascii")
            if key in _ID_KEYS and isinstance(item, str)
            else _hex_ids_to_base64(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_hex_ids_to_base64(item) for item in value]
    return value


def _encode(payload: dict[str, Any]) -> bytes:
    message = trace_service_pb2.ExportTraceServiceRequest()
    json_format.ParseDict(_hex_ids_to_base64(payload), message)
    return bytes(message.SerializeToString(deterministic=True))


def _per_span_requests(payload: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for resource_span in payload["resourceSpans"]:
        resource = {key: value for key, value in resource_span.items() if key != "scopeSpans"}
        for scope_span in resource_span["scopeSpans"]:
            scope = {key: value for key, value in scope_span.items() if key != "spans"}
            requests.extend(
                {"resourceSpans": [{**resource, "scopeSpans": [{**scope, "spans": [span]}]}]}
                for span in scope_span["spans"]
            )
    return requests


def _meaning(report: Any) -> dict[str, object]:
    return {key: value for key, value in report.items() if key != "warnings"}


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
def test_binary_request_and_collector_file_match_otlp_json(source: Path, tmp_path: Path) -> None:
    # Arrange
    payload = json.loads(source.read_text(encoding="utf-8"))
    body = tmp_path / "request.pb"
    body.write_bytes(_encode(payload))
    framed = tmp_path / "export.binpb"
    framed.write_bytes(
        b"".join(
            struct.pack(">I", len(encoded)) + encoded
            for encoded in (_encode(request) for request in _per_span_requests(payload))
        )
    )

    # Act
    expected = analyze_file(source, input_format="otlp-json")
    from_body = analyze_file(body, input_format="otlp-proto")
    from_file = analyze_file(framed, input_format="otlp-proto-file")

    # Assert
    assert _meaning(from_body.report) == _meaning(expected.report)
    assert _meaning(from_file.report) == _meaning(expected.report)
    assert from_body.dataset.events == expected.dataset.events
    assert from_file.dataset.events == expected.dataset.events
    codes = {warning["code"] for warning in from_file.report["warnings"]}  # type: ignore[index]
    assert "otlp_chronological_adjacency" in codes


def _single_span(**span: Any) -> dict[str, Any]:
    base = {
        "traceId": "0123456789abcdef0123456789abcdef",  # pragma: allowlist secret
        "spanId": "0123456789abcdef",
        "name": "step",
        "kind": 1,
        "startTimeUnixNano": "1790000000000000000",
        "endTimeUnixNano": "1790000000005000000",
        "attributes": [
            {"key": "count", "value": {"intValue": "-7"}},
            {"key": "ratio", "value": {"doubleValue": 0.5}},
            {"key": "flag", "value": {"boolValue": False}},
            {"key": "nested", "value": {"arrayValue": {"values": [{"stringValue": "x"}]}}},
        ],
        "status": {"code": 2, "message": "boom"},
    }
    base.update(span)
    return {"resourceSpans": [{"scopeSpans": [{"spans": [base]}]}]}


def test_scalar_attributes_status_and_unknown_fields_decode(tmp_path: Path) -> None:
    # Arrange: append an unknown field (number 99, varint) to the request bytes.
    path = tmp_path / "request.pb"
    path.write_bytes(_encode(_single_span()) + bytes([0x98, 0x06, 0x01]))

    # Act
    event = validate_file(path, input_format="otlp-proto").events[0]

    # Assert
    assert event.status == "error"
    assert event.trace_id == "0123456789abcdef0123456789abcdef"
    assert str(event.duration_ms) == "5"


@pytest.mark.parametrize(
    ("content", "code", "location"),
    [
        (b"\x0a\x05\x01", "malformed_otlp_proto", "byte 0"),
        (b"\x0a", "malformed_otlp_proto", "byte 1"),
        (b"\x08" + b"\xff" * 11, "malformed_otlp_proto", "byte 11"),
        (b"\x0f", "malformed_otlp_proto", "unsupported wire type 7"),
        (b"\x00\x01", "malformed_otlp_proto", "field number 0"),
        (b"\x09" + b"\x00" * 8, "malformed_otlp_proto", "wire type 1, expected 2"),
        (b"\x09\x01\x02", "malformed_otlp_proto", "fixed-width field is truncated"),
        (b"\x28\xb5\x2f\xfd\x00", "compressed_otlp_proto", "file"),
        (b"\x1f\x8b\x08", "compressed_otlp_proto", "file"),
    ],
)
def test_malformed_binary_requests_are_format_errors(
    content: bytes, code: str, location: str, tmp_path: Path
) -> None:
    path = tmp_path / "request.pb"
    path.write_bytes(content)
    with pytest.raises(FormatError) as caught:
        validate_file(path, input_format="otlp-proto")
    assert f"[{code}]" in str(caught.value)
    assert location in str(caught.value)


def test_invalid_utf8_names_are_format_errors(tmp_path: Path) -> None:
    encoded = _encode(_single_span(name="ab"))
    path = tmp_path / "request.pb"
    path.write_bytes(encoded.replace(b"ab", b"\xff\xfe", 1))
    with pytest.raises(FormatError, match="not valid UTF-8"):
        validate_file(path, input_format="otlp-proto")


@pytest.mark.parametrize(
    ("content", "code", "message"),
    [
        (b"", "empty_otlp_proto_file", "no length-prefixed"),
        (b"\x00\x00", "malformed_otlp_proto", "message 1.byte 0: length prefix is truncated"),
        (b"\x00\x00\x00\x09\x0a", "malformed_otlp_proto", "message length exceeds the file"),
        (b"\x00\x00\x00\x02\x0a\x05", "malformed_otlp_proto", "message 1.byte 4: length-delimited"),
        (
            b"\x00\x00\x00\x04\x28\xb5\x2f\xfd",
            "compressed_otlp_proto",
            "message 1.byte 4",
        ),
    ],
)
def test_malformed_collector_proto_files_are_format_errors(
    content: bytes, code: str, message: str, tmp_path: Path
) -> None:
    path = tmp_path / "export.binpb"
    path.write_bytes(content)
    with pytest.raises(FormatError) as caught:
        validate_file(path, input_format="otlp-proto-file")
    assert f"[{code}]" in str(caught.value)
    assert message in str(caught.value)
