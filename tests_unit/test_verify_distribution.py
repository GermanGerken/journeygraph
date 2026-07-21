from __future__ import annotations

import hashlib
import importlib
import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
verify_distribution = importlib.import_module("verify_distribution")
DistributionVerificationError = verify_distribution.DistributionVerificationError
ProjectIdentity = verify_distribution.ProjectIdentity
validate_release_tag = verify_distribution.validate_release_tag
verify_distributions = verify_distribution.verify_distributions
write_sha256_manifest = verify_distribution.write_sha256_manifest

IDENTITY = ProjectIdentity(name="journeygraph", version="0.2.0")
METADATA = b"Metadata-Version: 2.4\nName: journeygraph\nVersion: 0.2.0\n"


def _write_wheel(path: Path, *, unsafe_member: bool = False) -> None:
    required = {
        "journeygraph/py.typed": b"",
        "journeygraph/data/demo.jsonl": b"{}\n",
        "journeygraph/schemas/event-v1.schema.json": b"{}\n",
        "journeygraph/schemas/analysis-v1.schema.json": b"{}\n",
        "journeygraph-0.2.0.dist-info/licenses/LICENSE": b"license\n",
        "journeygraph-0.2.0.dist-info/METADATA": METADATA,
    }
    if unsafe_member:
        required["../outside"] = b"unsafe"
    with zipfile.ZipFile(path, mode="w") as archive:
        for name, contents in required.items():
            archive.writestr(name, contents)


def _write_sdist(path: Path) -> None:
    required = {
        "journeygraph-0.2.0/LICENSE": b"license\n",
        "journeygraph-0.2.0/README.md": b"readme\n",
        "journeygraph-0.2.0/pyproject.toml": b"[project]\n",
        "journeygraph-0.2.0/PKG-INFO": METADATA,
        "journeygraph-0.2.0/src/journeygraph/py.typed": b"",
        "journeygraph-0.2.0/src/journeygraph/data/demo.jsonl": b"{}\n",
        "journeygraph-0.2.0/src/journeygraph/schemas/event-v1.schema.json": b"{}\n",
        "journeygraph-0.2.0/src/journeygraph/schemas/analysis-v1.schema.json": b"{}\n",
    }
    with tarfile.open(path, mode="w:gz") as archive:
        for name, contents in required.items():
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            archive.addfile(member, io.BytesIO(contents))


def _write_distributions(dist_dir: Path, *, unsafe_wheel: bool = False) -> tuple[Path, Path]:
    wheel = dist_dir / "journeygraph-0.2.0-py3-none-any.whl"
    sdist = dist_dir / "journeygraph-0.2.0.tar.gz"
    _write_wheel(wheel, unsafe_member=unsafe_wheel)
    _write_sdist(sdist)
    return wheel, sdist


def test_release_tag_must_match_project_version() -> None:
    # Arrange
    mismatched_tag = "v0.1.9"

    # Act / Assert
    with pytest.raises(DistributionVerificationError, match="does not match"):
        validate_release_tag(mismatched_tag, IDENTITY)


def test_distributions_and_manifest_are_verified(tmp_path: Path) -> None:
    # Arrange
    wheel, sdist = _write_distributions(tmp_path)
    manifest = tmp_path / "evidence" / "sha256.txt"

    # Act
    actual = verify_distributions(tmp_path, IDENTITY)
    write_sha256_manifest(actual, manifest)

    # Assert
    assert actual == (wheel, sdist)
    assert manifest.read_text(encoding="utf-8").splitlines() == [
        f"{hashlib.sha256(wheel.read_bytes()).hexdigest()}  {wheel.name}",
        f"{hashlib.sha256(sdist.read_bytes()).hexdigest()}  {sdist.name}",
    ]


def test_unexpected_distribution_file_is_rejected(tmp_path: Path) -> None:
    # Arrange
    _write_distributions(tmp_path)
    (tmp_path / "notes.txt").write_text("not publishable", encoding="utf-8")

    # Act / Assert
    with pytest.raises(DistributionVerificationError, match="unexpected files"):
        verify_distributions(tmp_path, IDENTITY)


def test_mismatched_distribution_filename_is_rejected(tmp_path: Path) -> None:
    # Arrange
    wheel, _ = _write_distributions(tmp_path)
    wheel.rename(tmp_path / "other-0.2.0-py3-none-any.whl")

    # Act / Assert
    with pytest.raises(DistributionVerificationError, match="wheel filename"):
        verify_distributions(tmp_path, IDENTITY)


def test_unsafe_archive_member_is_rejected(tmp_path: Path) -> None:
    # Arrange
    _write_distributions(tmp_path, unsafe_wheel=True)

    # Act / Assert
    with pytest.raises(DistributionVerificationError, match="unsafe archive member"):
        verify_distributions(tmp_path, IDENTITY)
