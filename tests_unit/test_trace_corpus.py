from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
trace_corpus = importlib.import_module("trace_corpus")


def test_committed_otlp_corpus_passes_structural_provenance_and_disclosure_checks() -> None:
    # Arrange
    args = argparse.Namespace()

    # Act
    result = trace_corpus.check(args)

    # Assert
    assert result == 0


@pytest.mark.parametrize(
    "unsafe",
    [
        {"prompt.body": "redacted"},
        {"response": "redacted"},
        {"document.contents": "redacted"},
        {"tool_parameters": "redacted"},
        {"http.headers": "redacted"},
        {"authorization": "redacted"},
        {"cookie": "redacted"},
        {"user.id": "redacted"},
        {"session.id": "redacted"},
        {"safe": "person@example.com"},
        {"safe": "+1 (202) 555-0100"},
        {"safe": "/Users/example/private/input.json"},
        {"safe": "Bearer abcdefghijklmnop"},
    ],
)
def test_disclosure_scan_rejects_sensitive_keys_and_content_patterns(unsafe: object) -> None:
    # Arrange, Act, Assert
    with pytest.raises(trace_corpus.CorpusError):
        trace_corpus._scan_content(unsafe)


def test_disclosure_scan_allows_required_ids_and_semantic_counters() -> None:
    # Arrange
    safe = {
        "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "spanId": "1111111111111111",
        "attributes": [
            {"key": "llm.token_count.prompt", "value": {"intValue": "7"}},
            {"key": "gen_ai.usage.output_tokens", "value": {"intValue": "3"}},
        ],
    }

    # Act
    trace_corpus._scan_content(safe)

    # Assert
    assert safe["traceId"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
