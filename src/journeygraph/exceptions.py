"""User-facing exception types and stable CLI exit-code mapping."""

from __future__ import annotations

from collections.abc import Sequence

from journeygraph.domain.models import Issue

CHECK_FAILED_EXIT_CODE = 5
"""Exit code of ``journeygraph check`` when at least one rule fails."""


class JourneyGraphError(Exception):
    """Base class for expected, user-actionable failures."""

    exit_code = 1


class ValidationError(JourneyGraphError):
    """Input records violate the documented canonical contract."""

    exit_code = 2

    def __init__(self, issues: Sequence[Issue]) -> None:
        self.issues = tuple(issues)
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        header = f"validation failed with {len(self.issues)} error(s)"
        return "\n".join([header, *(issue.format() for issue in self.issues)])


class FormatError(JourneyGraphError):
    """A file cannot be decoded as its selected input format."""

    exit_code = 2


class UsageError(JourneyGraphError):
    """A command-line option or configuration file is invalid."""

    exit_code = 2


class FileOperationError(JourneyGraphError):
    """A filesystem operation failed."""

    exit_code = 3


class OutputConflictError(JourneyGraphError):
    """An output path is unsafe or would overwrite data without permission."""

    exit_code = 4
