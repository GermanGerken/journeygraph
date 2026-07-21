from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
verify_distribution = importlib.import_module("verify_distribution")
verify_published = importlib.import_module("verify_published")
DistributionVerificationError = verify_distribution.DistributionVerificationError
ProjectIdentity = verify_distribution.ProjectIdentity
PublishedWheel = verify_published.PublishedWheel
read_sha256_manifest = verify_published.read_sha256_manifest
verify_downloaded_wheel = verify_published.verify_downloaded_wheel
verify_pypi_payload = verify_published.verify_pypi_payload

IDENTITY = ProjectIdentity(name="journeygraph", version="0.2.0")
WHEEL_HASH = "a" * 64
SDIST_HASH = "b" * 64
WHEEL_URL = "https://files.pythonhosted.org/packages/example/journeygraph-0.2.0-py3-none-any.whl"
EXPECTED = {
    "journeygraph-0.2.0-py3-none-any.whl": WHEEL_HASH,
    "journeygraph-0.2.0.tar.gz": SDIST_HASH,
}


def _payload(*, wheel_hash: str = WHEEL_HASH, wheel_url: str = WHEEL_URL) -> dict[str, object]:
    return {
        "info": {"version": "0.2.0"},
        "urls": [
            {
                "filename": "journeygraph-0.2.0-py3-none-any.whl",
                "digests": {"sha256": wheel_hash},
                "url": wheel_url,
            },
            {
                "filename": "journeygraph-0.2.0.tar.gz",
                "digests": {"sha256": SDIST_HASH},
            },
        ],
    }


def test_manifest_and_pypi_hashes_match(tmp_path: Path) -> None:
    # Arrange
    manifest = tmp_path / "release-sha256.txt"
    manifest.write_text(
        "\n".join(f"{digest}  {filename}" for filename, digest in EXPECTED.items()) + "\n",
        encoding="utf-8",
    )

    # Act
    actual = read_sha256_manifest(manifest)
    wheel = verify_pypi_payload(_payload(), IDENTITY, actual)

    # Assert
    assert actual == EXPECTED
    assert wheel == PublishedWheel(
        filename="journeygraph-0.2.0-py3-none-any.whl",
        url=WHEEL_URL,
        sha256=WHEEL_HASH,
    )


def test_invalid_manifest_entry_is_rejected(tmp_path: Path) -> None:
    # Arrange
    manifest = tmp_path / "release-sha256.txt"
    manifest.write_text("not-a-hash  artifact.whl\n", encoding="utf-8")

    # Act / Assert
    with pytest.raises(DistributionVerificationError, match="invalid SHA-256"):
        read_sha256_manifest(manifest)


def test_changed_pypi_hash_is_rejected() -> None:
    # Arrange
    changed_payload = _payload(wheel_hash="c" * 64)

    # Act / Assert
    with pytest.raises(DistributionVerificationError, match="differ"):
        verify_pypi_payload(changed_payload, IDENTITY, EXPECTED)


def test_unofficial_wheel_url_is_rejected() -> None:
    # Arrange
    unofficial_payload = _payload(
        wheel_url="https://example.invalid/journeygraph-0.2.0-py3-none-any.whl"
    )

    # Act / Assert
    with pytest.raises(DistributionVerificationError, match="exact official file URL"):
        verify_pypi_payload(unofficial_payload, IDENTITY, EXPECTED)


def test_incomplete_release_manifest_is_rejected() -> None:
    # Arrange
    wheel_only = {"journeygraph-0.2.0-py3-none-any.whl": WHEEL_HASH}

    # Act / Assert
    with pytest.raises(DistributionVerificationError, match="exactly one wheel"):
        verify_pypi_payload(_payload(), IDENTITY, wheel_only)


def test_downloaded_wheel_hash_must_match_build_manifest(tmp_path: Path) -> None:
    # Arrange
    wheel = PublishedWheel(
        filename="journeygraph-0.2.0-py3-none-any.whl",
        url=WHEEL_URL,
        sha256=WHEEL_HASH,
    )
    downloaded = tmp_path / wheel.filename
    downloaded.write_bytes(b"different bytes")

    # Act / Assert
    with pytest.raises(DistributionVerificationError, match="downloaded wheel hash differs"):
        verify_downloaded_wheel(downloaded, wheel)


def test_downloaded_wheel_hash_can_match_build_manifest(tmp_path: Path) -> None:
    # Arrange
    contents = b"verified wheel bytes"
    downloaded = tmp_path / "journeygraph-0.2.0-py3-none-any.whl"
    downloaded.write_bytes(contents)
    wheel = PublishedWheel(
        filename=downloaded.name,
        url=WHEEL_URL,
        sha256=hashlib.sha256(contents).hexdigest(),
    )

    # Act / Assert
    verify_downloaded_wheel(downloaded, wheel)
