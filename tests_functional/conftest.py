from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests_functional.helpers import (
    CommandResult,
    find_journeygraph_executable,
    run_cli,
)


@pytest.fixture(scope="session")
def journeygraph_executable() -> Path:
    return find_journeygraph_executable()


@pytest.fixture
def cli(
    journeygraph_executable: Path,
) -> Callable[..., CommandResult]:
    def invoke(*arguments: str | Path, cwd: Path | None = None) -> CommandResult:
        return run_cli(journeygraph_executable, *arguments, cwd=cwd)

    return invoke


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return Path(__file__).with_name("fixtures")
