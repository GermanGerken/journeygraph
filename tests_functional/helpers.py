"""Language-agnostic helpers for exercising the installed CLI and its artifacts.

Nothing in this module imports :mod:`journeygraph`.  The helpers intentionally know only
the public executable, file formats, and report contracts described by the MVP ExecPlan.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from copy import deepcopy
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_ARTIFACTS = {
    "analysis.json",
    "normalized.jsonl",
    "report.html",
    "graph.svg",
}
ANALYSIS_PUBLIC_KEYS = {
    "schema_version",
    "tool_version",
    "config",
    "totals",
    "outcomes",
    "nodes",
    "transitions",
    "entries",
    "terminals",
    "paths",
    "retries",
    "loops",
    "failure_points",
    "dropoff_points",
    "path_comparison",
    "cohorts",
    "metrics",
    "warnings",
}


@dataclass(frozen=True)
class CommandResult:
    """Captured outcome from one real ``journeygraph`` process."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    def assert_exit(self, expected: int) -> None:
        assert self.returncode == expected, (
            f"expected exit {expected}, got {self.returncode}\n"
            f"command: {' '.join(self.args)}\n"
            f"stdout:\n{self.stdout}\n"
            f"stderr:\n{self.stderr}"
        )


def find_journeygraph_executable() -> Path:
    """Locate a real console-script executable, never a module import fallback."""

    candidates: list[str | Path | None] = [os.environ.get("JOURNEYGRAPH_EXECUTABLE")]
    if os.name == "nt":  # pragma: no cover - exercised by the Windows CI job
        candidates.extend(
            [
                REPOSITORY_ROOT / ".venv" / "Scripts" / "journeygraph.exe",
                Path(sys.prefix) / "Scripts" / "journeygraph.exe",
            ]
        )
    else:
        candidates.extend(
            [
                REPOSITORY_ROOT / ".venv" / "bin" / "journeygraph",
                Path(sys.prefix) / "bin" / "journeygraph",
            ]
        )
    candidates.append(shutil.which("journeygraph"))

    for candidate in candidates:
        if not candidate:
            continue
        resolved = Path(candidate).expanduser().resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved

    raise AssertionError(
        "The functional suite requires the installed `journeygraph` executable. "
        "Install the project (normally `python -m pip install -e .`) or set "
        "JOURNEYGRAPH_EXECUTABLE to the console-script path."
    )


def run_cli(
    executable: Path,
    *arguments: str | Path,
    cwd: Path | None = None,
    timeout: float = 30.0,
) -> CommandResult:
    """Run the public executable in a fresh process and capture UTF-8 streams."""

    command = (str(executable), *(str(argument) for argument in arguments))
    environment = os.environ.copy()
    environment.update({"PYTHONUTF8": "1", "NO_COLOR": "1"})
    completed = subprocess.run(
        command,
        cwd=cwd or REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        args=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path.name} must contain a JSON object"
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        assert isinstance(value, dict), f"{path.name}:{line_number} is not an object"
        records.append(value)
    return records


def assert_analysis_artifacts(output_dir: Path) -> dict[str, Any]:
    actual = {path.name for path in output_dir.iterdir() if path.is_file()}
    missing = ANALYSIS_ARTIFACTS - actual
    assert not missing, f"missing analysis artifacts: {sorted(missing)}"

    for name in ANALYSIS_ARTIFACTS:
        artifact = output_dir / name
        assert artifact.stat().st_size > 0, f"{name} must not be empty"

    analysis = read_json(output_dir / "analysis.json")
    missing_keys = ANALYSIS_PUBLIC_KEYS - analysis.keys()
    assert not missing_keys, f"analysis.json is missing public keys: {sorted(missing_keys)}"
    assert analysis.get("schema_version") == "1.0"
    assert isinstance(analysis.get("tool_version"), str) and analysis["tool_version"]
    assert isinstance(analysis.get("config"), dict)
    return analysis


def node_labels(analysis: dict[str, Any]) -> dict[str, tuple[str, str]]:
    nodes = analysis.get("nodes")
    assert isinstance(nodes, list), "analysis.nodes must be a list"
    labels: dict[str, tuple[str, str]] = {}
    for node in nodes:
        assert isinstance(node, dict)
        node_id = node.get("id")
        operation_type = node.get("operation_type")
        component = node.get("component")
        assert isinstance(node_id, str) and node_id
        assert isinstance(operation_type, str) and operation_type
        assert isinstance(component, str) and component
        labels[node_id] = (operation_type, component)
    assert len(labels) == len(nodes), "node IDs must be unique"
    return labels


def transition_counts(
    analysis: dict[str, Any],
) -> dict[tuple[tuple[str, str], tuple[str, str]], tuple[int, int]]:
    labels = node_labels(analysis)
    transitions = analysis.get("transitions")
    assert isinstance(transitions, list), "analysis.transitions must be a list"
    result: dict[tuple[tuple[str, str], tuple[str, str]], tuple[int, int]] = {}
    for edge in transitions:
        assert isinstance(edge, dict)
        source_id = edge.get("source")
        target_id = edge.get("target")
        assert source_id in labels and target_id in labels
        weight = edge.get("weight")
        trace_count = edge.get("trace_count")
        assert isinstance(weight, int) and weight > 0
        assert isinstance(trace_count, int) and 0 < trace_count <= weight
        assert edge.get("source_label") == ":".join(labels[source_id])
        assert edge.get("target_label") == ":".join(labels[target_id])
        result[(labels[source_id], labels[target_id])] = (weight, trace_count)
    assert len(result) == len(transitions), "transition identities must be unique"
    return result


def _path_node_ids(path: dict[str, Any]) -> list[str]:
    value = path.get("node_ids", path.get("nodes"))
    assert isinstance(value, list) and all(isinstance(item, str) for item in value)
    return value


def _count(record: dict[str, Any]) -> int:
    value = record.get("trace_count", record.get("count", record.get("frequency")))
    assert isinstance(value, int) and value > 0
    return value


def path_counts(
    analysis: dict[str, Any],
) -> dict[tuple[tuple[str, str], ...], tuple[int, dict[str, int]]]:
    labels = node_labels(analysis)
    paths = analysis.get("paths")
    assert isinstance(paths, list), "analysis.paths must be a list"
    result: dict[tuple[tuple[str, str], ...], tuple[int, dict[str, int]]] = {}
    for path in paths:
        assert isinstance(path, dict)
        node_ids = _path_node_ids(path)
        assert node_ids and all(node_id in labels for node_id in node_ids)
        expected_labels = [":".join(labels[node_id]) for node_id in node_ids]
        assert path.get("labels") == expected_labels
        raw_outcomes = path.get("outcomes", path.get("outcome_counts", {}))
        outcomes = _counts_by_name(raw_outcomes, name_key="outcome")
        result[tuple(labels[node_id] for node_id in node_ids)] = (_count(path), outcomes)
    assert len(result) == len(paths), "exact path identities must be unique"
    return result


def totals(analysis: dict[str, Any]) -> dict[str, Any]:
    value = analysis.get("totals")
    assert isinstance(value, dict), "analysis.totals must be an object"
    return value


def outcome_counts(analysis: dict[str, Any]) -> dict[str, int]:
    outcome_section = analysis.get("outcomes")
    if outcome_section is None:
        outcome_section = totals(analysis).get("outcomes")
    return _counts_by_name(outcome_section, name_key="outcome")


def _counts_by_name(value: Any, *, name_key: str) -> dict[str, int]:
    if isinstance(value, dict) and "counts" in value:
        value = value["counts"]
    if isinstance(value, list):
        converted: dict[str, int] = {}
        for item in value:
            assert isinstance(item, dict)
            name = item.get(name_key)
            count = item.get("count")
            assert isinstance(name, str) and isinstance(count, int) and count >= 0
            if count:
                converted[name] = count
        return converted
    assert isinstance(value, dict), "analysis must expose reconciled outcome counts"
    assert all(
        isinstance(name, str) and isinstance(count, int) and count >= 0
        for name, count in value.items()
    )
    return {name: count for name, count in value.items() if count}


def warning_codes(analysis: dict[str, Any]) -> list[str]:
    warnings = analysis.get("warnings")
    assert isinstance(warnings, list), "analysis.warnings must be a list"
    result: list[str] = []
    for warning in warnings:
        assert isinstance(warning, dict)
        code = warning.get("code")
        assert isinstance(code, str) and code
        result.append(code)
    return result


def analysis_meaning(analysis: dict[str, Any]) -> dict[str, Any]:
    """Remove source-order diagnostics while retaining all analytical meaning."""

    value = deepcopy(analysis)
    value.pop("warnings", None)
    value.pop("issues", None)
    total_values = value.get("totals")
    if isinstance(total_values, dict):
        total_values.pop("input_records", None)
        total_values.pop("warnings", None)
    return value


def assert_no_traceback(result: CommandResult) -> None:
    combined = f"{result.stdout}\n{result.stderr}".lower()
    assert "traceback (most recent call last)" not in combined


class HTMLInspection(HTMLParser):
    """Small structural inspector; it deliberately does not execute browser behavior."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.start_tags: list[tuple[str, dict[str, str | None]]] = []
        self.attributes: list[tuple[str, str, str | None]] = []
        self.text_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        self.tags.append(lowered)
        self.start_tags.append((lowered, {name.lower(): value for name, value in attrs}))
        self.attributes.extend((lowered, name.lower(), value) for name, value in attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        self.text_chunks.append(data)

    @property
    def text(self) -> str:
        return "".join(self.text_chunks)


def inspect_static_html(path: Path) -> HTMLInspection:
    raw = path.read_text(encoding="utf-8")
    parser = HTMLInspection()
    parser.feed(raw)
    parser.close()

    assert "html" in parser.tags and "body" in parser.tags
    script_attributes = [attrs for tag, attrs in parser.start_tags if tag == "script"]
    assert all(
        attrs.get("type", "").lower() == "application/json" and "src" not in attrs
        for attrs in script_attributes
    ), "the static report must contain no executable or external scripts"
    assert not any(name.startswith("on") for _, name, _ in parser.attributes)
    for _, name, value in parser.attributes:
        if name in {"href", "src", "action"} and value:
            lowered = value.strip().lower()
            assert not lowered.startswith(("http://", "https://", "//", "javascript:"))

    csp_values = [
        value
        for tag, name, value in parser.attributes
        if tag == "meta" and name == "content" and value and "default-src" in value
    ]
    assert csp_values, "the report must carry a restrictive Content Security Policy"
    assert any("'none'" in value for value in csp_values)
    return parser


def inspect_safe_svg(path: Path) -> ET.Element:
    raw = path.read_text(encoding="utf-8")
    root = ET.fromstring(raw)
    assert root.tag.rsplit("}", 1)[-1].lower() == "svg"
    assert "<script" not in raw.lower(), "escaped input became executable SVG"

    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1].lower()
        assert local_name not in {"script", "foreignobject"}
        for qualified_name, value in element.attrib.items():
            attribute = qualified_name.rsplit("}", 1)[-1].lower()
            assert not attribute.startswith("on")
            if attribute == "href":
                lowered = value.strip().lower()
                assert not lowered.startswith(("http://", "https://", "//", "javascript:"))
    return root


def artifact_text(output_dir: Path) -> str:
    return "\n".join(
        (output_dir / name).read_text(encoding="utf-8") for name in sorted(ANALYSIS_ARTIFACTS)
    )
