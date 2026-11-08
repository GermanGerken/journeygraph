"""Standard-library decoder for binary OTLP trace protobuf.

The decoder reads only the fields the OTLP/JSON importer uses and rebuilds the official
OTLP/JSON request structure (hex identifiers, integer enums, decimal-string 64-bit integers,
``AnyValue`` wrappers), so both encodings share one span mapping.  Field numbers follow
opentelemetry-proto v1.10.0.  Unknown fields are skipped as the wire format requires.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

from journeygraph.domain.models import SourceRecord
from journeygraph.exceptions import FormatError
from journeygraph.ingestion.otlp import _format_error, _request_records

_VARINT, _I64, _LEN, _I32 = 0, 1, 2, 5
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_GZIP_MAGIC = b"\x1f\x8b"
_PREFIX = struct.Struct(">I")
_DOUBLE = struct.Struct("<d")

Message = dict[str, object]


class _Malformed(Exception):
    def __init__(self, offset: int, message: str) -> None:
        super().__init__(message)
        self.offset = offset
        self.message = message


def _fields(data: bytes, start: int, end: int) -> Iterator[tuple[int, int, object, int]]:
    """Yield ``(field number, wire type, value, offset)`` for one message in ``data[start:end]``.

    Varints yield ints, fixed-width fields yield their raw little-endian bytes, and
    length-delimited fields yield ``(start, end)`` offsets into ``data``.
    """

    position = start
    while position < end:
        offset = position
        key, position = _varint(data, position, end)
        field_number, wire_type = key >> 3, key & 7
        if field_number == 0:
            raise _Malformed(offset, "field number 0 is invalid")
        if wire_type == _VARINT:
            value, position = _varint(data, position, end)
            yield field_number, wire_type, value, offset
        elif wire_type in {_I64, _I32}:
            width = 8 if wire_type == _I64 else 4
            if position + width > end:
                raise _Malformed(offset, "fixed-width field is truncated")
            yield field_number, wire_type, data[position : position + width], offset
            position += width
        elif wire_type == _LEN:
            length, position = _varint(data, position, end)
            if position + length > end:
                raise _Malformed(offset, "length-delimited field exceeds its message")
            yield field_number, wire_type, (position, position + length), offset
            position += length
        else:
            raise _Malformed(offset, f"unsupported wire type {wire_type}")


def _varint(data: bytes, position: int, end: int) -> tuple[int, int]:
    result = 0
    for shift in range(0, 70, 7):
        if position >= end:
            raise _Malformed(position, "varint is truncated")
        byte = data[position]
        position += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, position
    raise _Malformed(position, "varint is longer than 10 bytes")


def _expect(wire_type: int, expected: int, offset: int, name: str) -> None:
    if wire_type != expected:
        raise _Malformed(offset, f"{name} has wire type {wire_type}, expected {expected}")


def _span_of(value: object) -> tuple[int, int]:
    return cast(tuple[int, int], value)  # guaranteed by _expect(_LEN)


def _text(data: bytes, value: object, offset: int) -> str:
    start, end = _span_of(value)
    try:
        return data[start:end].decode("utf-8")
    except UnicodeDecodeError:
        raise _Malformed(offset, "string field is not valid UTF-8") from None


def _signed(value: int) -> int:
    value &= (1 << 64) - 1
    return value - (1 << 64) if value >= 1 << 63 else value


def _repeated(data: bytes, value: object, decode: Callable[[bytes, int, int], Message]) -> Message:
    start, end = _span_of(value)
    return decode(data, start, end)


def _any_value(data: bytes, start: int, end: int) -> Message:
    result: Message = {}
    for number, wire_type, value, offset in _fields(data, start, end):
        if number == 1:
            _expect(wire_type, _LEN, offset, "AnyValue.string_value")
            result = {"stringValue": _text(data, value, offset)}
        elif number == 2:
            _expect(wire_type, _VARINT, offset, "AnyValue.bool_value")
            result = {"boolValue": value != 0}
        elif number == 3:
            _expect(wire_type, _VARINT, offset, "AnyValue.int_value")
            result = {"intValue": str(_signed(cast(int, value)))}
        elif number == 4:
            _expect(wire_type, _I64, offset, "AnyValue.double_value")
            result = {"doubleValue": _DOUBLE.unpack(cast(bytes, value))[0]}
        elif number in {5, 6, 7}:
            # The importer does not retain nested or binary values, so their contents are
            # not decoded; this also bounds recursion on hostile input.
            _expect(wire_type, _LEN, offset, "AnyValue nested value")
            result = {("arrayValue", "kvlistValue", "bytesValue")[number - 5]: {}}
        elif number == 8:
            result = {}
    return result


def _key_value(data: bytes, start: int, end: int) -> Message:
    result: Message = {}
    for number, wire_type, value, offset in _fields(data, start, end):
        if number == 1:
            _expect(wire_type, _LEN, offset, "KeyValue.key")
            result["key"] = _text(data, value, offset)
        elif number == 2:
            _expect(wire_type, _LEN, offset, "KeyValue.value")
            result["value"] = _repeated(data, value, _any_value)
    return result


def _attributes(data: bytes, start: int, end: int, number_of_attributes: int) -> list[Message]:
    attributes: list[Message] = []
    for number, wire_type, value, offset in _fields(data, start, end):
        if number == number_of_attributes:
            _expect(wire_type, _LEN, offset, "attributes")
            attributes.append(_repeated(data, value, _key_value))
    return attributes


def _hex(data: bytes, value: object) -> str:
    start, end = _span_of(value)
    return data[start:end].hex()


def _fixed64(value: object) -> str:
    return str(int.from_bytes(cast(bytes, value), "little"))


def _status(data: bytes, start: int, end: int) -> Message:
    result: Message = {}
    for number, wire_type, value, offset in _fields(data, start, end):
        if number == 2:
            _expect(wire_type, _LEN, offset, "Status.message")
            result["message"] = _text(data, value, offset)
        elif number == 3:
            _expect(wire_type, _VARINT, offset, "Status.code")
            result["code"] = _signed(cast(int, value))
    return result


def _span(data: bytes, start: int, end: int) -> Message:
    result: Message = {}
    attributes: list[Message] = []
    for number, wire_type, value, offset in _fields(data, start, end):
        if number in {1, 2, 4}:
            _expect(wire_type, _LEN, offset, "span identifier")
            key = {1: "traceId", 2: "spanId", 4: "parentSpanId"}[number]
            identifier = _hex(data, value)
            if identifier:
                result[key] = identifier
        elif number == 5:
            _expect(wire_type, _LEN, offset, "Span.name")
            result["name"] = _text(data, value, offset)
        elif number == 6:
            _expect(wire_type, _VARINT, offset, "Span.kind")
            result["kind"] = _signed(cast(int, value))
        elif number in {7, 8}:
            _expect(wire_type, _I64, offset, "span timestamp")
            result["startTimeUnixNano" if number == 7 else "endTimeUnixNano"] = _fixed64(value)
        elif number == 9:
            _expect(wire_type, _LEN, offset, "Span.attributes")
            attributes.append(_repeated(data, value, _key_value))
        elif number == 15:
            _expect(wire_type, _LEN, offset, "Span.status")
            result["status"] = _repeated(data, value, _status)
    if attributes:
        result["attributes"] = attributes
    return result


def _scope_spans(data: bytes, start: int, end: int) -> Message:
    spans: list[Message] = []
    for number, wire_type, value, offset in _fields(data, start, end):
        if number == 2:
            _expect(wire_type, _LEN, offset, "ScopeSpans.spans")
            spans.append(_repeated(data, value, _span))
    return {"spans": spans} if spans else {}


def _resource(data: bytes, start: int, end: int) -> Message:
    attributes = _attributes(data, start, end, 1)
    return {"attributes": attributes} if attributes else {}


def _resource_spans(data: bytes, start: int, end: int) -> Message:
    result: Message = {}
    scopes: list[Message] = []
    for number, wire_type, value, offset in _fields(data, start, end):
        if number == 1:
            _expect(wire_type, _LEN, offset, "ResourceSpans.resource")
            result["resource"] = _repeated(data, value, _resource)
        elif number == 2:
            _expect(wire_type, _LEN, offset, "ResourceSpans.scope_spans")
            scopes.append(_repeated(data, value, _scope_spans))
    if scopes:
        result["scopeSpans"] = scopes
    return result


def decode_request(data: bytes, start: int = 0, end: int | None = None) -> Message:
    """Decode one ``ExportTraceServiceRequest`` (or ``TracesData``) into OTLP/JSON structure."""

    stop = len(data) if end is None else end
    resource_spans: list[Message] = []
    for number, wire_type, value, offset in _fields(data, start, stop):
        if number == 1:
            _expect(wire_type, _LEN, offset, "resource_spans")
            resource_spans.append(_repeated(data, value, _resource_spans))
    return {"resourceSpans": resource_spans}


def _malformed(error: _Malformed, prefix: str) -> FormatError:
    location = f"{prefix}byte {error.offset}"
    return _format_error(
        "malformed_otlp_proto",
        location,
        error.message,
        "provide uncompressed binary OTLP trace protobuf",
    )


def _compressed(data: bytes, location: str) -> FormatError | None:
    if data.startswith(_ZSTD_MAGIC) or data.startswith(_GZIP_MAGIC):
        return _format_error(
            "compressed_otlp_proto",
            location,
            "input is zstd or gzip compressed",
            "decompress the file first, or export without compression",
        )
    return None


def read_otlp_proto(path: Path) -> tuple[SourceRecord, ...]:
    """Read one uncompressed binary ``ExportTraceServiceRequest`` (an OTLP/HTTP body)."""

    data = path.read_bytes()
    compressed = _compressed(data, "file")
    if compressed is not None:
        raise compressed
    try:
        payload = decode_request(data)
    except _Malformed as error:
        raise _malformed(error, "") from None
    records: list[SourceRecord] = []
    _request_records(payload, "", records)
    return tuple(records)


def read_otlp_proto_file(path: Path) -> tuple[SourceRecord, ...]:
    """Read Collector file-exporter ``format: proto`` output: length-prefixed messages."""

    data = path.read_bytes()
    compressed = _compressed(data, "file")
    if compressed is not None:
        raise compressed
    if not data:
        raise _format_error(
            "empty_otlp_proto_file",
            "file",
            "no length-prefixed OTLP messages were found",
            "provide Collector file-exporter output written with format: proto",
        )
    records: list[SourceRecord] = []
    position, message = 0, 0
    while position < len(data):
        message += 1
        prefix = f"message {message}."
        if position + _PREFIX.size > len(data):
            raise _format_error(
                "malformed_otlp_proto",
                f"{prefix}byte {position}",
                "length prefix is truncated",
                "provide complete 4-byte big-endian length prefixes",
            )
        (length,) = _PREFIX.unpack_from(data, position)
        start = position + _PREFIX.size
        end = start + length
        if end > len(data):
            raise _format_error(
                "malformed_otlp_proto",
                f"{prefix}byte {position}",
                "message length exceeds the file",
                "provide complete length-prefixed messages",
            )
        compressed = _compressed(data[start:end], f"{prefix}byte {start}")
        if compressed is not None:
            raise compressed
        try:
            payload = decode_request(data, start, end)
        except _Malformed as error:
            raise _malformed(error, prefix) from None
        _request_records(payload, f"message {message}", records)
        position = end
    return tuple(records)
