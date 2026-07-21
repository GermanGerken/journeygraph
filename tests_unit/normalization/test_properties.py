from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from journeygraph.normalization.privacy import filter_metadata


@settings(max_examples=50, deadline=None)
@given(
    key=st.text(
        alphabet=st.characters(
            blacklist_categories=("Cc", "Cs"),
            blacklist_characters=".[]",
        ),
        min_size=1,
        max_size=30,
    ),
    value=st.text(max_size=80),
)
def test_metadata_outside_allowlist_never_appears_in_output(key: str, value: str) -> None:
    # Arrange
    allowed = {"cohort"}

    # Act
    retained, _warnings = filter_metadata({key: value}, allowed_keys=allowed, location="metadata")

    # Assert
    if key.casefold() != "cohort":
        assert value not in retained.values()
