"""Conservative metadata allowlisting shared by every importer."""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Mapping

from journeygraph.domain.models import Issue

DEFAULT_METADATA_ALLOWLIST = frozenset(
    {"agent", "cohort", "environment", "model", "region", "service", "version", "workflow"}
)

_SENSITIVE_FRAGMENTS = frozenset(
    {
        "address",
        "account_id",
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "body",
        "choice",
        "cookie",
        "credit_card",
        "customer_id",
        "document",
        "email",
        "embedding",
        "employee_id",
        "first_name",
        "full_name",
        "input_value",
        "last_name",
        "message",
        "output_value",
        "password",
        "passwd",
        "personal",
        "phone",
        "prompt",
        "refresh_token",
        "response",
        "secret",
        "session_id",
        "ssn",
        "tool_argument",
        "token",
        "user_id",
        "username",
        "visitor_id",
    }
)
_KEY_NORMALIZER = re.compile(r"[^a-z0-9]+")


def normalize_metadata_key(key: str) -> str:
    """Normalize a metadata key for policy comparison, not for output."""

    return _KEY_NORMALIZER.sub("_", key.casefold()).strip("_")


def is_sensitive_key(key: str) -> bool:
    """Return whether a key is permanently denied."""

    normalized = normalize_metadata_key(key)
    return any(fragment in normalized for fragment in _SENSITIVE_FRAGMENTS)


def is_safe_unicode_text(value: str) -> bool:
    """Return whether text is valid UTF-8/XML-safe Unicode scalar content."""

    return all(
        codepoint in {0x09, 0x0A, 0x0D}
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
        for codepoint in map(ord, value)
    )


def filter_metadata(
    value: object,
    *,
    allowed_keys: Collection[str],
    location: str,
) -> tuple[dict[str, str | int | float | bool | None], list[Issue]]:
    """Retain only scalar allowlisted metadata and return safe warnings."""

    if value is None:
        return {}, []
    if not isinstance(value, Mapping):
        return {}, [
            Issue(
                "warning",
                "metadata_excluded",
                location,
                "metadata is not an object and was excluded",
                "provide a JSON object containing allowlisted scalar operational fields",
            )
        ]

    normalized_allowed = {normalize_metadata_key(key) for key in allowed_keys}
    retained: dict[str, str | int | float | bool | None] = {}
    seen_allowed_keys: set[str] = set()
    ambiguous_keys: set[str] = set()
    warnings: list[Issue] = []
    for field_index, (raw_key, raw_value) in enumerate(
        sorted(value.items(), key=lambda item: str(item[0])),
        start=1,
    ):
        if not isinstance(raw_key, str):
            warnings.append(
                Issue(
                    "warning",
                    "metadata_key_excluded",
                    location,
                    "a non-string metadata key was excluded",
                    "use short string keys from the documented allowlist",
                )
            )
            continue
        key_location = f"{location}[{field_index}]"
        normalized_key = normalize_metadata_key(raw_key)
        if is_sensitive_key(raw_key):
            warnings.append(
                Issue(
                    "warning",
                    "sensitive_metadata_excluded",
                    key_location,
                    "a privacy-sensitive metadata field was excluded",
                    "remove sensitive content before analysis; this key cannot be allowlisted",
                )
            )
            continue
        if normalized_key not in normalized_allowed:
            warnings.append(
                Issue(
                    "warning",
                    "unknown_metadata_excluded",
                    key_location,
                    "metadata outside the explicit allowlist was excluded",
                    "remove the field or pass --allow-metadata-key for safe operational data",
                )
            )
            continue
        if normalized_key in seen_allowed_keys:
            retained.pop(normalized_key, None)
            if normalized_key not in ambiguous_keys:
                warnings.append(
                    Issue(
                        "warning",
                        "metadata_key_collision",
                        key_location,
                        "multiple metadata fields normalize to the same key and were excluded",
                        "provide at most one spelling for each allowlisted operational key",
                    )
                )
                ambiguous_keys.add(normalized_key)
            continue
        seen_allowed_keys.add(normalized_key)
        if raw_value is not None and not isinstance(raw_value, (str, int, float, bool)):
            warnings.append(
                Issue(
                    "warning",
                    "nested_metadata_excluded",
                    key_location,
                    "nested metadata was excluded",
                    "use a scalar string, number, boolean, or null value",
                )
            )
            continue
        if isinstance(raw_value, float) and not math.isfinite(raw_value):
            warnings.append(
                Issue(
                    "warning",
                    "non_finite_metadata_excluded",
                    key_location,
                    "non-finite numeric metadata was excluded",
                    "use a finite number or remove the field",
                )
            )
            continue
        if isinstance(raw_value, str) and len(raw_value) > 512:
            warnings.append(
                Issue(
                    "warning",
                    "long_metadata_excluded",
                    key_location,
                    "an oversized metadata value was excluded",
                    "use a short operational category no longer than 512 characters",
                )
            )
            continue
        if isinstance(raw_value, str) and not is_safe_unicode_text(raw_value):
            warnings.append(
                Issue(
                    "warning",
                    "invalid_unicode_metadata_excluded",
                    key_location,
                    "metadata containing invalid Unicode/XML characters was excluded",
                    "use ordinary Unicode text without control characters or surrogate code points",
                )
            )
            continue
        retained[normalized_key] = raw_value
    return retained, warnings
