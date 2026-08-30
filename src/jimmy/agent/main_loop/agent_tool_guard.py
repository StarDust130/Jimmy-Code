from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jimmy.state.session import SessionState


@dataclass(frozen=True, slots=True)
class ToolGuardDecision:
    """
    Result of deterministic runtime policy validation.
    """

    allowed: bool
    reason: str = ""


class ToolGuard:
    """
    Very small runtime policy guard.

    IMPORTANT:

    This guard does NOT:
    - understand natural-language task scope
    - parse "commit all"
    - decide which files the user meant
    - decide whether a task is complete
    - call the LLM

    It only blocks objectively invalid tool usage.
    """

    def __init__(
        self,
        workspace: Path,
    ) -> None:
        self.workspace = workspace.resolve()

    def check(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        state: SessionState,
    ) -> ToolGuardDecision:
        """
        Validate hard runtime rules.

        `state` remains part of the interface so future
        runtime policies can inspect state without making
        the guard responsible for task understanding.
        """

        del state

        if (
            not isinstance(
                tool_name,
                str,
            )
            or not tool_name.strip()
        ):
            return self._deny(
                "Tool name is required.",
            )

        if tool_name == "run_shell":
            return self._check_run_shell(
                arguments,
            )

        if tool_name == "create_files":
            return self._check_create_files(
                arguments,
            )

        if tool_name == "edit_file":
            return self._check_edit_file(
                arguments,
            )

        # Every other tool owns its own argument/runtime
        # validation.
        return ToolGuardDecision(
            allowed=True,
        )

    # =========================================================
    # SHELL
    # =========================================================

    def _check_run_shell(
        self,
        arguments: dict[str, Any],
    ) -> ToolGuardDecision:
        command = arguments.get(
            "command",
            "",
        )

        if not isinstance(
            command,
            str,
        ):
            return self._deny(
                "run_shell requires a string command.",
            )

        command = command.strip()

        if not command:
            return self._deny(
                "run_shell requires a non-empty command.",
            )

        # Git mutation belongs to the dedicated Git tool.
        #
        # IMPORTANT:
        # We deliberately do NOT block generic shell writes,
        # mkdir, npm, python, package managers, generators,
        # build tools, etc.
        #
        # A real coding agent needs shell flexibility.
        if self._is_git_mutation(
            command,
        ):
            return self._deny(
                "Use git_commit for Git mutations instead of run_shell.",
            )

        return ToolGuardDecision(
            allowed=True,
        )

    # =========================================================
    # CREATE FILES
    # =========================================================

    def _check_create_files(
        self,
        arguments: dict[str, Any],
    ) -> ToolGuardDecision:
        files = arguments.get(
            "files",
        )

        if not isinstance(
            files,
            list,
        ):
            return self._deny(
                "create_files requires a files list.",
            )

        for item in files:
            if not isinstance(
                item,
                dict,
            ):
                return self._deny(
                    "Each created file must be an object.",
                )

            raw_path = item.get(
                "path",
                "",
            )

            if (
                not isinstance(
                    raw_path,
                    str,
                )
                or not raw_path.strip()
            ):
                return self._deny(
                    "Each created file requires a path.",
                )

            try:
                path = self._resolve(
                    raw_path,
                )
            except ValueError as exc:
                return self._deny(
                    str(exc),
                )

            if path.exists():
                return self._deny(
                    (f"'{raw_path}' already exists. Use edit_file for existing files."),
                )

        return ToolGuardDecision(
            allowed=True,
        )

    # =========================================================
    # EDIT FILE
    # =========================================================

    def _check_edit_file(
        self,
        arguments: dict[str, Any],
    ) -> ToolGuardDecision:
        raw_path = arguments.get(
            "path",
            "",
        )

        if (
            not isinstance(
                raw_path,
                str,
            )
            or not raw_path.strip()
        ):
            return self._deny(
                "edit_file requires a valid path.",
            )

        try:
            path = self._resolve(
                raw_path,
            )
        except ValueError as exc:
            return self._deny(
                str(exc),
            )

        if not path.exists():
            return self._deny(
                (f"'{raw_path}' does not exist. Use create_files for new files."),
            )

        if not path.is_file():
            return self._deny(
                f"'{raw_path}' is not a file.",
            )

        return ToolGuardDecision(
            allowed=True,
        )

    # =========================================================
    # PATH SAFETY
    # =========================================================

    def _resolve(
        self,
        relative_path: str,
    ) -> Path:
        candidate = (self.workspace / relative_path).resolve()

        try:
            candidate.relative_to(
                self.workspace,
            )
        except ValueError as exc:
            raise ValueError(
                f"Path escapes workspace: {relative_path}",
            ) from exc

        return candidate

    # =========================================================
    # GIT DETECTION
    # =========================================================

    @staticmethod
    def _is_git_mutation(
        command: str,
    ) -> bool:
        """
        Detect Git commands that mutate repository state.

        Read-only Git commands remain allowed.
        """

        return bool(
            re.search(
                r"(?i)"
                r"(?:^|[;&|])\s*"
                r"(?:git\s+)"
                r"(?:add|commit|reset|restore|checkout|switch|clean|rebase|merge|cherry-pick|revert|rm)\b",
                command,
            ),
        )

    @staticmethod
    def _deny(
        reason: str,
    ) -> ToolGuardDecision:
        return ToolGuardDecision(
            allowed=False,
            reason=reason,
        )
