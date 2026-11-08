"""Exact structural tests for the standard-library OTLP protobuf decoder."""

from __future__ import annotations

import base64
import struct
from pathlib import Path
from typing import Any

import pytest

from journeygraph.ingestion.otlp_proto import decode_request, read_otlp_proto_file

trace_service_pb2 = pytest.importorskip("opentelemetry.proto.collector.trace.v1.trace_service_pb2")
json_format = pytest.importorskip("google.protobuf.json_format")

_TRACE = "0123456789abcdef0123456789abcdef"  # pragma: allowlist secret
_SPAN = "0123456789abcdef"
_PARENT = "fedcba9876543210"  # pragma: allowlist secret


def _encode(payload: dict[str, Any]) -> bytes:
    def convert(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: base64.b64encode(bytes.fromhex(item)).decode("ascii")
                if key in {"traceId", "spanId", "parentSpanId"}
                else convert(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    message = trace_service_pb2.ExportTraceServiceRequest()
    json_format.ParseDict(convert(payload), message)
    return bytes(message.SerializeToString(deterministic=True))


_ATTRIBUTES = [
    {"key": "text", "value": {"stringValue": "héllo"}},
    {"key": "empty", "value": {"stringValue": ""}},
    {"key": "flag", "value": {"boolValue": False}},
    {"key": "yes", "value": {"boolValue": True}},
    {"key": "small", "value": {"intValue": "-7"}},
    {"key": "large", "value": {"intValue": "9223372036854775807"}},
    {"key": "lowest", "value": {"intValue": "-9223372036854775808"}},
    {"key": "ratio", "value": {"doubleValue": -0.25}},
    {"key": "list", "value": {"arrayValue": {"values": [{"stringValue": "x"}]}}},
    {"key": "map", "value": {"kvlistValue": {"values": []}}},
    {"key": "blob", "value": {"bytesValue": "AAE="}},
    {"key": "unset"},
]


def test_decoded_structure_matches_the_otlp_json_shape() -> None:
    # Arrange
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "api"}}]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "ignored-scope"},
                        "spans": [
                            {
                                "traceId": _TRACE,
                                "spanId": _SPAN,
                                "parentSpanId": _PARENT,
                                "name": "step",
                                "kind": 3,
                                "startTimeUnixNano": "1790000000000000001",
                                "endTimeUnixNano": "18446744073709551615",
                                "attributes": _ATTRIBUTES,
                                "status": {"code": 2, "message": "boom"},
                            },
                            {"traceId": _TRACE, "spanId": _PARENT, "name": "root"},
                        ],
                    },
                    {"scope": {"name": "no-spans"}},
                ],
            },
            {},
        ]
    }

    # Act
    decoded = decode_request(_encode(payload))

    # Assert
    assert decoded == {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "api"}}]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": _TRACE,
                                "spanId": _SPAN,
                                "parentSpanId": _PARENT,
                                "name": "step",
                                "kind": 3,
                                "startTimeUnixNano": "1790000000000000001",
                                "endTimeUnixNano": "18446744073709551615",
                                "attributes": [
                                    {"key": "text", "value": {"stringValue": "héllo"}},
                                    {"key": "empty", "value": {"stringValue": ""}},
                                    {"key": "flag", "value": {"boolValue": False}},
                                    {"key": "yes", "value": {"boolValue": True}},
                                    {"key": "small", "value": {"intValue": "-7"}},
                                    {"key": "large", "value": {"intValue": "9223372036854775807"}},
                                    {
                                        "key": "lowest",
                                        "value": {"intValue": "-9223372036854775808"},
                                    },
                                    {"key": "ratio", "value": {"doubleValue": -0.25}},
                                    {"key": "list", "value": {"arrayValue": {}}},
                                    {"key": "map", "value": {"kvlistValue": {}}},
                                    {"key": "blob", "value": {"bytesValue": {}}},
                                    {"key": "unset"},
                                ],
                                "status": {"code": 2, "message": "boom"},
                            },
                            {"traceId": _TRACE, "spanId": _PARENT, "name": "root"},
                        ]
                    },
                    {},
                ],
            },
            {},
        ]
    }


def test_empty_request_and_unknown_fields_decode_to_nothing() -> None:
    assert decode_request(b"") == {"resourceSpans": []}
    unknown = bytes([0x98, 0x06, 0x01, 0x22, 0x01, 0x00, 0x2D, 1, 2, 3, 4, 0x31]) + bytes(8)
    assert decode_request(unknown) == {"resourceSpans": []}


def test_negative_enum_values_are_sign_extended() -> None:
    # A negative int32 enum is encoded as a ten-byte varint.
    span = bytes([0x30]) + bytes([0xFF] * 9 + [0x01])
    body = _len_field(1, _len_field(2, _len_field(2, span)))
    decoded = decode_request(body)
    assert decoded["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["kind"] == -1  # type: ignore[index]


def _len_field(number: int, payload: bytes) -> bytes:
    return bytes([(number << 3) | 2, len(payload)]) + payload


def test_collector_files_number_messages_in_locations(tmp_path: Path) -> None:
    # Arrange: two valid messages, the second with a span missing its name.
    first = _encode(
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": _TRACE,
                                    "spanId": _SPAN,
                                    "name": "a",
                                    "startTimeUnixNano": "1",
                                    "endTimeUnixNano": "2",
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    )
    second = _encode(
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": _TRACE,
                                    "spanId": _PARENT,
                                    "startTimeUnixNano": "1",
                                    "endTimeUnixNano": "2",
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    )
    path = tmp_path / "export.binpb"
    path.write_bytes(b"".join(struct.pack(">I", len(item)) + item for item in (first, second)))

    # Act / Assert
    with pytest.raises(
        Exception, match=r"message 2\.resourceSpans\[0\]\.scopeSpans\[0\]\.spans\[0\]\.name"
    ):
        read_otlp_proto_file(path)
    path.write_bytes(struct.pack(">I", len(first)) + first)
    records = read_otlp_proto_file(path)
    assert [record.location for record in records] == [
        "message 1.resourceSpans[0].scopeSpans[0].spans[0]"
    ]
    path.write_bytes(bytes(4) + struct.pack(">I", len(first)) + first)
    assert len(read_otlp_proto_file(path)) == 1
