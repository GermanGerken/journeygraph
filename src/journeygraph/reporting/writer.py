"""Safe filesystem publication for rendered analysis artifacts."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from journeygraph.domain.models import NormalizedDataset
from journeygraph.exceptions import FileOperationError, OutputConflictError
from journeygraph.normalization.pipeline import serialize_normalized_jsonl
from journeygraph.reporting.html import render_html
from journeygraph.reporting.serialize import serialize_analysis
from journeygraph.reporting.svg import render_svg


@dataclass(frozen=True, slots=True)
class AnalysisArtifacts:
    """Paths written by one successful analysis publication."""

    output_dir: Path
    analysis_json: Path
    normalized_jsonl: Path
    html_report: Path
    svg_graph: Path
    extra_files: tuple[Path, ...] = ()


def validate_output_path(path: Path) -> None:
    """Reject explicit traversal and symlink output roots."""

    if ".." in path.parts:
        raise OutputConflictError(
            f"unsafe output path contains '..': {path}. Fix: choose a direct destination path"
        )
    if path.is_symlink():
        raise OutputConflictError(
            f"unsafe output path is a symbolic link: {path}. Fix: choose a real directory or file"
        )


def _same_file_or_alias(candidate: Path, source: Path) -> bool:
    """Detect lexical, symlink, hard-link, and case-insensitive filesystem aliases."""

    if candidate.resolve() == source.resolve():
        return True
    try:
        return candidate.samefile(source)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise FileOperationError(
            f"cannot verify output collision for {candidate}: {error.strerror or error}"
        ) from error


def _prepare_directory(path: Path, *, force: bool) -> None:
    validate_output_path(path)
    if path.exists() and not path.is_dir():
        raise OutputConflictError(
            f"output path exists and is not a directory: {path}. Fix: choose another directory"
        )
    if path.exists() and any(path.iterdir()) and not force:
        raise OutputConflictError(
            f"output directory is not empty: {path}. Fix: choose an empty directory or pass --force"
        )
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise FileOperationError(
            f"cannot create output directory {path}: {error.strerror or error}"
        ) from error


def _atomic_write(path: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as target:
            temporary = Path(target.name)
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        temporary.replace(path)
    except (OSError, UnicodeError) as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise FileOperationError(
            f"cannot write output file {path}: {getattr(error, 'strerror', None) or error}"
        ) from error


def write_text_file(
    path: str | Path,
    content: str,
    *,
    force: bool,
    input_path: str | Path | None = None,
) -> Path:
    """Write one UTF-8 file with traversal, collision, and overwrite protection."""

    output_path = Path(path)
    validate_output_path(output_path)
    if input_path is not None and _same_file_or_alias(output_path, Path(input_path)):
        raise OutputConflictError(
            f"output path would overwrite the input file: {output_path}. Fix: choose another path"
        )
    if output_path.exists() and not force:
        raise OutputConflictError(
            f"output file already exists: {output_path}. Fix: choose another path or pass --force"
        )
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise FileOperationError(
            f"cannot create output parent {output_path.parent}: {error.strerror or error}"
        ) from error
    _atomic_write(output_path, content)
    return output_path


def write_analysis_artifacts(
    report: Mapping[str, object],
    dataset: NormalizedDataset,
    output_dir: str | Path,
    *,
    force: bool = False,
    extra_files: Mapping[str, str] | None = None,
    input_path: str | Path | None = None,
) -> AnalysisArtifacts:
    """Render everything first, then publish fixed-name artifacts."""

    rendered: dict[str, str] = {
        "analysis.json": serialize_analysis(report),
        "normalized.jsonl": serialize_normalized_jsonl(dataset),
        "report.html": render_html(report),
        "graph.svg": render_svg(report),
    }
    for name, content in (extra_files or {}).items():
        candidate = Path(name)
        if candidate.name != name or name in rendered:
            raise OutputConflictError(
                f"unsafe extra artifact name: {name!r}. Fix: use one plain unique filename"
            )
        rendered[name] = content

    target = Path(output_dir)
    if input_path is not None:
        source = Path(input_path)
        collisions = [name for name in rendered if _same_file_or_alias(target / name, source)]
        if collisions:
            raise OutputConflictError(
                f"input/artifact collision at {source.resolve()}. "
                "Fix: choose an output directory that does not contain the input file"
            )
    _prepare_directory(target, force=force)
    for name, content in rendered.items():
        _atomic_write(target / name, content)
    extra_paths = tuple(target / name for name in sorted((extra_files or {}).keys()))
    return AnalysisArtifacts(
        output_dir=target,
        analysis_json=target / "analysis.json",
        normalized_jsonl=target / "normalized.jsonl",
        html_report=target / "report.html",
        svg_graph=target / "graph.svg",
        extra_files=extra_paths,
    )
