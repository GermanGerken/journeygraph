from __future__ import annotations

from journeygraph.normalization.privacy import (
    DEFAULT_METADATA_ALLOWLIST,
    filter_metadata,
    is_safe_unicode_text,
    is_sensitive_key,
    normalize_metadata_key,
)


def test_metadata_policy_retains_only_safe_allowlisted_scalars() -> None:
    # Arrange
    metadata = {
        "Agent": "planner",
        "api-key": "never emit",
        "custom": "excluded by default",
        "region": {"nested": "excluded"},
        "version": float("inf"),
        "workflow": "x" * 513,
        7: "invalid key",
    }

    # Act
    retained, warnings = filter_metadata(
        metadata,
        allowed_keys=DEFAULT_METADATA_ALLOWLIST,
        location="line 1.metadata",
    )

    # Assert
    assert retained == {"agent": "planner"}
    assert {warning.code for warning in warnings} == {
        "long_metadata_excluded",
        "metadata_key_excluded",
        "nested_metadata_excluded",
        "non_finite_metadata_excluded",
        "sensitive_metadata_excluded",
        "unknown_metadata_excluded",
    }
    assert all("never emit" not in warning.format() for warning in warnings)


def test_metadata_policy_handles_absent_and_non_object_values() -> None:
    # Arrange
    allowed = {"cohort"}

    # Act
    absent = filter_metadata(None, allowed_keys=allowed, location="metadata")
    invalid = filter_metadata(["cohort"], allowed_keys=allowed, location="metadata")

    # Assert
    assert absent == ({}, [])
    assert invalid[0] == {}
    assert [issue.code for issue in invalid[1]] == ["metadata_excluded"]
    assert [issue.severity for issue in invalid[1]] == ["warning"]


def test_metadata_policy_preserves_deterministic_warning_locations() -> None:
    # Arrange
    metadata = {
        "workflow": {"nested": "value"},
        "cohort": "x" * 513,
        "agent": float("inf"),
    }

    # Act
    retained, warnings = filter_metadata(
        metadata,
        allowed_keys=DEFAULT_METADATA_ALLOWLIST,
        location="line 1.metadata",
    )

    # Assert
    assert retained == {}
    assert [(warning.location, warning.code, warning.severity) for warning in warnings] == [
        ("line 1.metadata[1]", "non_finite_metadata_excluded", "warning"),
        ("line 1.metadata[2]", "long_metadata_excluded", "warning"),
        ("line 1.metadata[3]", "nested_metadata_excluded", "warning"),
    ]


def test_sensitive_key_detection_is_normalized_and_non_overridable() -> None:
    # Arrange
    keys = (
        "Authorization",
        "user.id",
        "session-id",
        "access-token",
        "PROMPT.text",
        "customer-id",
        "account.id",
        "username",
    )

    # Act
    decisions = [is_sensitive_key(key) for key in keys]

    # Assert
    assert decisions == [True] * len(keys)
    assert normalize_metadata_key("Deployment.Environment.Name") == "deployment_environment_name"
    assert not is_sensitive_key("environment")


def test_unicode_policy_accepts_xml_scalar_ranges_and_rejects_invalid_codepoints() -> None:
    # Arrange
    accepted = (
        "plain",
        "\t\n\r",
        "\ud7ff",
        "\ue000",
        "\ufffd",
        "\U00010000",
        "emoji \U0001f680",
        "\U0010ffff",
    )
    rejected = ("bad\x00", "bad\x01", "bad\x0b", "bad\x0e", "\ud800", "\ufffe", "\uffff")

    # Act
    accepted_decisions = [is_safe_unicode_text(value) for value in accepted]
    rejected_decisions = [is_safe_unicode_text(value) for value in rejected]

    # Assert
    assert accepted_decisions == [True] * len(accepted)
    assert rejected_decisions == [False] * len(rejected)


def test_metadata_value_boundaries_do_not_discard_later_safe_fields() -> None:
    # Arrange
    metadata = {
        "agent": "x" * 513,
        "region": "north",
        "workflow": "w" * 512,
    }

    # Act
    retained, warnings = filter_metadata(
        metadata,
        allowed_keys=DEFAULT_METADATA_ALLOWLIST,
        location="metadata",
    )

    # Assert
    assert retained == {"region": "north", "workflow": "w" * 512}
    assert [(warning.code, warning.location) for warning in warnings] == [
        ("long_metadata_excluded", "metadata[1]")
    ]


def test_rejected_metadata_never_echoes_raw_keys_or_invalid_unicode() -> None:
    # Arrange
    sentinel_key = "prompt_PRIVATE_KEY_SENTINEL"
    metadata = {
        sentinel_key: "private value",
        "unknown_PRIVATE_FIELD_SENTINEL": "private value",
        "cohort": "bad\x01value",
        "region": chr(0xD800),
    }

    # Act
    retained, warnings = filter_metadata(
        metadata,
        allowed_keys=DEFAULT_METADATA_ALLOWLIST,
        location="line 1.metadata",
    )
    rendered = "\n".join(warning.format() for warning in warnings)

    # Assert
    assert retained == {}
    assert sentinel_key not in rendered
    assert "PRIVATE_FIELD_SENTINEL" not in rendered
    assert {warning.code for warning in warnings} == {
        "invalid_unicode_metadata_excluded",
        "sensitive_metadata_excluded",
        "unknown_metadata_excluded",
    }
