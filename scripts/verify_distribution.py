"""Verify a release tag and the exact wheel and sdist selected for publication."""

from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
import tomllib
import zipfile
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
WHEEL_REQUIRED_SUFFIXES = (
    "journeygraph/py.typed",
    "journeygraph/data/demo.jsonl",
    "journeygraph/schemas/event-v1.schema.json",
    "journeygraph/schemas/analysis-v1.schema.json",
    ".dist-info/licenses/LICENSE",
)
SDIST_REQUIRED_SUFFIXES = (
    "/LICENSE",
    "/README.md",
    "/pyproject.toml",
    "/src/journeygraph/py.typed",
    "/src/journeygraph/data/demo.jsonl",
    "/src/journeygraph/schemas/event-v1.schema.json",
    "/src/journeygraph/schemas/analysis-v1.schema.json",
)


class DistributionVerificationError(ValueError):
    """Raised when a release identity or built distribution is unsafe or inconsistent."""


@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    """Package identity read from the authoritative project metadata."""

    name: str
    version: str


def load_project_identity(root: Path = ROOT) -> ProjectIdentity:
    """Read and validate the package name and version from ``pyproject.toml``."""

    document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project_value: object = document.get("project")
    if not isinstance(project_value, dict):
        raise DistributionVerificationError("pyproject.toml has no [project] table")
    name = project_value.get("name")
    version = project_value.get("version")
    if not isinstance(name, str) or not name:
        raise DistributionVerificationError("project name must be a non-empty string")
    if not isinstance(version, str) or not version:
        raise DistributionVerificationError("project version must be a non-empty string")
    return ProjectIdentity(name=name, version=version)


def validate_release_tag(tag: str, identity: ProjectIdentity) -> None:
    """Require the immutable release tag to match the package version exactly."""

    expected = f"v{identity.version}"
    if tag != expected:
        raise DistributionVerificationError(
            f"release tag {tag!r} does not match project version tag {expected!r}"
        )


def _normalized_name(value: str) -> str:
    return value.lower().replace("-", "_").replace(".", "_")


def _validate_member_names(names: list[str], archive: Path) -> None:
    for name in names:
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts:
            raise DistributionVerificationError(
                f"{archive.name} contains an unsafe archive member: {name!r}"
            )


def _require_suffixes(names: list[str], suffixes: tuple[str, ...], archive: Path) -> None:
    missing = [suffix for suffix in suffixes if not any(name.endswith(suffix) for name in names)]
    if missing:
        raise DistributionVerificationError(
            f"{archive.name} is missing required packaged content: {', '.join(missing)}"
        )


def _validate_metadata(data: bytes, identity: ProjectIdentity, archive: Path) -> None:
    message = BytesParser(policy=policy.default).parsebytes(data)
    name = message.get("Name")
    version = message.get("Version")
    if not isinstance(name, str) or _normalized_name(name) != _normalized_name(identity.name):
        raise DistributionVerificationError(
            f"{archive.name} metadata name {name!r} does not match {identity.name!r}"
        )
    if not isinstance(version, str) or version != identity.version:
        raise DistributionVerificationError(
            f"{archive.name} metadata version {version!r} does not match {identity.version!r}"
        )


def _verify_wheel(wheel: Path, identity: ProjectIdentity) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        _validate_member_names(names, wheel)
        _require_suffixes(names, WHEEL_REQUIRED_SUFFIXES, wheel)
        metadata_members = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_members) != 1:
            raise DistributionVerificationError(
                f"{wheel.name} must contain exactly one .dist-info/METADATA file"
            )
        _validate_metadata(archive.read(metadata_members[0]), identity, wheel)


def _verify_sdist(sdist: Path, identity: ProjectIdentity) -> None:
    with tarfile.open(sdist, mode="r:gz") as archive:
        names = archive.getnames()
        _validate_member_names(names, sdist)
        _require_suffixes(names, SDIST_REQUIRED_SUFFIXES, sdist)
        metadata_members = [
            member
            for member in archive.getmembers()
            if member.isfile() and member.name.endswith("/PKG-INFO") and member.name.count("/") == 1
        ]
        if len(metadata_members) != 1:
            raise DistributionVerificationError(
                f"{sdist.name} must contain exactly one top-level PKG-INFO file"
            )
        extracted = archive.extractfile(metadata_members[0])
        if extracted is None:
            raise DistributionVerificationError(f"cannot read metadata from {sdist.name}")
        _validate_metadata(extracted.read(), identity, sdist)


def verify_distributions(dist_dir: Path, identity: ProjectIdentity) -> tuple[Path, Path]:
    """Verify that ``dist_dir`` contains one exact wheel and one exact sdist."""

    files = sorted(path for path in dist_dir.iterdir() if path.is_file())
    wheels = [path for path in files if path.suffix == ".whl"]
    sdists = [path for path in files if path.name.endswith(".tar.gz")]
    unexpected = [path.name for path in files if path not in wheels and path not in sdists]
    if unexpected:
        raise DistributionVerificationError(
            f"dist directory contains unexpected files: {', '.join(unexpected)}"
        )
    if len(wheels) != 1 or len(sdists) != 1 or len(files) != 2:
        raise DistributionVerificationError(
            "dist directory must contain exactly one wheel and one .tar.gz source distribution"
        )
    wheel, sdist = wheels[0], sdists[0]
    filename_name = _normalized_name(identity.name)
    filename_version = identity.version.replace("-", "_")
    if not wheel.name.startswith(f"{filename_name}-{filename_version}-"):
        raise DistributionVerificationError(
            f"wheel filename {wheel.name!r} does not match {identity.name} {identity.version}"
        )
    expected_sdist = f"{filename_name}-{identity.version}.tar.gz"
    if sdist.name != expected_sdist:
        raise DistributionVerificationError(
            f"sdist filename {sdist.name!r} does not match {expected_sdist!r}"
        )
    _verify_wheel(wheel, identity)
    _verify_sdist(sdist, identity)
    return wheel, sdist


def write_sha256_manifest(distributions: tuple[Path, Path], destination: Path) -> None:
    """Write a deterministic SHA-256 manifest outside the publishable ``dist`` directory."""

    lines = []
    for distribution in sorted(distributions, key=lambda path: path.name):
        digest = hashlib.sha256(distribution.read_bytes()).hexdigest()
        lines.append(f"{digest}  {distribution.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    """Validate release identity, archive contents, metadata, and file hashes."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Authorized release tag, for example v0.1.1")
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "artifacts/release-sha256.txt",
    )
    arguments = parser.parse_args()

    try:
        identity = load_project_identity()
        validate_release_tag(arguments.tag, identity)
        distributions = verify_distributions(arguments.dist_dir, identity)
        write_sha256_manifest(distributions, arguments.manifest)
    except (DistributionVerificationError, OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"release verification error: {error}", file=sys.stderr)
        return 1

    print(
        f"release distributions verified: {identity.name} {identity.version}; "
        f"manifest={arguments.manifest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
