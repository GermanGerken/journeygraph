"""Verify PyPI hashes and a clean installation after an authorized publication."""

from __future__ import annotations

import argparse
import json
import os
import re

# Commands use fixed executable paths and argument vectors without a shell.
import subprocess  # nosec B404
import sys
import tempfile
import time
import urllib.error
import urllib.request
import venv
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from verify_distribution import (
    DistributionVerificationError,
    ProjectIdentity,
    load_project_identity,
    validate_release_tag,
)

SHA256 = re.compile(r"^[0-9a-f]{64}$")
PYPI_JSON_ROOT = "https://pypi.org/pypi"


@dataclass(frozen=True, slots=True)
class PublishedWheel:
    """Exact wheel identity selected from the verified PyPI response."""

    filename: str
    url: str
    sha256: str


def read_sha256_manifest(path: Path) -> dict[str, str]:
    """Parse the deterministic build manifest as ``filename -> sha256``."""

    hashes: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        parts = line.split("  ", maxsplit=1)
        if len(parts) != 2 or not SHA256.fullmatch(parts[0]) or not parts[1]:
            raise DistributionVerificationError(
                f"invalid SHA-256 manifest entry on line {line_number}"
            )
        digest, filename = parts
        if Path(filename).name != filename:
            raise DistributionVerificationError(
                f"manifest line {line_number} contains a non-basename filename"
            )
        if filename in hashes:
            raise DistributionVerificationError(f"duplicate manifest filename: {filename}")
        hashes[filename] = digest
    if not hashes:
        raise DistributionVerificationError("SHA-256 manifest is empty")
    return hashes


def verify_pypi_payload(
    payload: dict[str, object], identity: ProjectIdentity, expected: dict[str, str]
) -> PublishedWheel:
    """Require PyPI metadata to match and return the exact wheel to download."""

    wheels = [filename for filename in expected if filename.endswith(".whl")]
    sdists = [filename for filename in expected if filename.endswith(".tar.gz")]
    if len(expected) != 2 or len(wheels) != 1 or len(sdists) != 1:
        raise DistributionVerificationError(
            "release manifest must contain exactly one wheel and one source distribution"
        )
    info_value = payload.get("info")
    if not isinstance(info_value, dict) or info_value.get("version") != identity.version:
        raise DistributionVerificationError("PyPI response version does not match the release")
    urls_value = payload.get("urls")
    if not isinstance(urls_value, list):
        raise DistributionVerificationError("PyPI response has no release file list")

    published: dict[str, str] = {}
    wheel_url: str | None = None
    for item in urls_value:
        if not isinstance(item, dict):
            raise DistributionVerificationError("PyPI release file entry is not an object")
        filename = item.get("filename")
        digests = item.get("digests")
        if not isinstance(filename, str) or not isinstance(digests, dict):
            raise DistributionVerificationError("PyPI release file entry is incomplete")
        digest = digests.get("sha256")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise DistributionVerificationError(f"PyPI has no valid SHA-256 for {filename!r}")
        if filename in published:
            raise DistributionVerificationError(f"PyPI returned a duplicate file: {filename}")
        published[filename] = digest
        if filename == wheels[0]:
            url = item.get("url")
            if not isinstance(url, str):
                raise DistributionVerificationError("PyPI wheel entry has no download URL")
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "files.pythonhosted.org"
                or Path(unquote(parsed.path)).name != filename
            ):
                raise DistributionVerificationError(
                    "PyPI wheel URL is not an exact official file URL"
                )
            wheel_url = url

    if published != expected:
        raise DistributionVerificationError(
            "PyPI filenames or hashes differ from the verified build manifest"
        )
    if wheel_url is None:
        raise DistributionVerificationError("PyPI response did not identify the verified wheel")
    return PublishedWheel(filename=wheels[0], url=wheel_url, sha256=expected[wheels[0]])


def fetch_pypi_payload(
    identity: ProjectIdentity, *, attempts: int = 6, delay_seconds: float = 10.0
) -> dict[str, object]:
    """Fetch the version-specific PyPI JSON response with bounded propagation retries."""

    project = quote(identity.name, safe="")
    version = quote(identity.version, safe="")
    url = f"{PYPI_JSON_ROOT}/{project}/{version}/json"
    request = urllib.request.Request(url, headers={"User-Agent": "journeygraph-release-verifier"})
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # nosec B310
                payload: object = json.loads(response.read())
            if not isinstance(payload, dict):
                raise DistributionVerificationError("PyPI JSON response is not an object")
            return payload
        except (urllib.error.HTTPError, urllib.error.URLError) as error:
            last_error = error
            if attempt == attempts:
                break
            time.sleep(delay_seconds)
    raise DistributionVerificationError(
        f"PyPI version metadata was unavailable after {attempts} attempts: {last_error}"
    )


def _executable(environment_dir: Path, name: str) -> Path:
    scripts = environment_dir / ("Scripts" if os.name == "nt" else "bin")
    return scripts / f"{name}{'.exe' if os.name == 'nt' else ''}"


def verify_downloaded_wheel(path: Path, wheel: PublishedWheel) -> None:
    """Require downloaded wheel bytes to match the build-time SHA-256 digest."""

    actual = sha256(path.read_bytes()).hexdigest()
    if actual != wheel.sha256:
        raise DistributionVerificationError(
            f"downloaded wheel hash differs for {wheel.filename}: {actual}"
        )


def _download_verified_wheel(wheel: PublishedWheel, destination: Path) -> None:
    request = urllib.request.Request(
        wheel.url, headers={"User-Agent": "journeygraph-release-verifier"}
    )
    with (
        urllib.request.urlopen(request, timeout=60) as response,  # nosec B310
        destination.open("wb") as output,
    ):
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    verify_downloaded_wheel(destination, wheel)


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> str:
    # Every command is a fixed executable argument vector.
    completed = subprocess.run(  # nosec B603
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    if completed.returncode != 0:
        raise DistributionVerificationError(
            f"published-package command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def verify_fresh_install(identity: ProjectIdentity, wheel: PublishedWheel) -> None:
    """Hash, install, and exercise the exact wheel downloaded from PyPI."""

    with tempfile.TemporaryDirectory(prefix="journeygraph-pypi-") as temporary:
        scratch = Path(temporary)
        wheel_path = scratch / wheel.filename
        _download_verified_wheel(wheel, wheel_path)
        environment_dir = scratch / "venv"
        venv.EnvBuilder(with_pip=True, clear=True, system_site_packages=False).create(
            environment_dir
        )
        python = _executable(environment_dir, "python")
        cli = _executable(environment_dir, "journeygraph")
        environment = os.environ.copy()
        for name in (
            "PYTHONHOME",
            "PYTHONPATH",
            "COVERAGE_PROCESS_START",
            "COV_CORE_SOURCE",
            "COV_CORE_CONFIG",
            "COV_CORE_DATAFILE",
        ):
            environment.pop(name, None)
        environment["PYTHONUTF8"] = "1"
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "--retries",
                "5",
                "--timeout",
                "20",
                "--index-url",
                "https://pypi.org/simple",
                "--only-binary=:all:",
                str(wheel_path),
            ],
            cwd=scratch,
            environment=environment,
        )
        for arguments in (["--help"], ["validate", "--help"], ["analyze", "--help"]):
            _run([str(cli), *arguments], cwd=scratch, environment=environment)
        module_path = _run(
            [str(python), "-c", "import journeygraph; print(journeygraph.__file__)"],
            cwd=scratch,
            environment=environment,
        ).strip()
        if "site-packages" not in module_path:
            raise DistributionVerificationError(
                f"published wheel import did not resolve from site-packages: {module_path}"
            )
        installed_version = _run(
            [str(python), "-c", "import journeygraph; print(journeygraph.__version__)"],
            cwd=scratch,
            environment=environment,
        ).strip()
        if installed_version != identity.version:
            raise DistributionVerificationError(
                f"installed package version {installed_version!r} differs from {identity.version!r}"
            )
        output = scratch / "demo"
        _run(
            [str(cli), "demo", "--output-dir", str(output)],
            cwd=scratch,
            environment=environment,
        )
        expected = {
            "analysis.json",
            "demo-traces.jsonl",
            "graph.svg",
            "normalized.jsonl",
            "report.html",
        }
        actual = {path.name for path in output.iterdir() if path.is_file()}
        if actual != expected:
            raise DistributionVerificationError(
                f"published demo artifacts differ: expected {expected}, got {actual}"
            )


def main() -> int:
    """Verify PyPI metadata/hashes and the exact version's clean-install journey."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Authorized release tag")
    parser.add_argument("--manifest", type=Path, required=True)
    arguments = parser.parse_args()

    try:
        identity = load_project_identity()
        validate_release_tag(arguments.tag, identity)
        expected = read_sha256_manifest(arguments.manifest)
        payload = fetch_pypi_payload(identity)
        wheel = verify_pypi_payload(payload, identity, expected)
        verify_fresh_install(identity, wheel)
    except (DistributionVerificationError, OSError, subprocess.TimeoutExpired) as error:
        print(f"published release verification error: {error}", file=sys.stderr)
        return 1

    print(f"published release verified: {identity.name} {identity.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
