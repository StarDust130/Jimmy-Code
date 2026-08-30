from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jimmy.state.session import SessionState


@dataclass(frozen=True, slots=True)
class ToolGuardDecision:
    """Deterministic result of tool validation."""

    allowed: bool
    reason: str = ""


class ToolGuard:
    """
    Lightweight deterministic guard for obvious tool mistakes.

    Important:
    - Never calls the LLM.
    - Never decides whether a task is complete.
    - Never replaces normal tool execution.
    - Only blocks actions that clearly contradict the workspace
      or the user's explicit request.
    """

    def __init__(
        self,
        workspace: Path,
    ) -> None:
        self.workspace = workspace

    def check(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        state: SessionState,
    ) -> ToolGuardDecision:
        if tool_name == "create_files":
            return self._check_create_files(arguments)

        if tool_name == "edit_file":
            return self._check_edit_file(arguments)

        if tool_name == "run_shell":
            return self._check_run_shell(arguments)

        if tool_name == "git_commit":
            return self._check_git_commit(
                arguments,
                state,
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
        raw_files = arguments.get(
            "files",
            [],
        )

        if not isinstance(raw_files, list):
            return self._deny("create_files requires a 'files' list.")

        for item in raw_files:
            if not isinstance(item, dict):
                return self._deny("Each create_files entry must be an object.")

            raw_path = item.get(
                "path",
                "",
            )

            if not isinstance(raw_path, str) or not raw_path.strip():
                return self._deny("Every file needs a valid path.")

            path = self._resolve(raw_path)

            if path.exists():
                return self._deny(
                    f"'{raw_path}' already exists. Use edit_file to modify an existing file."
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

        if not isinstance(raw_path, str) or not raw_path.strip():
            return self._deny("edit_file requires a valid file path.")

        path = self._resolve(raw_path)

        if not path.exists():
            return self._deny(
                f"'{raw_path}' does not exist. Use create_files when creating a new file."
            )

        if not path.is_file():
            return self._deny(f"'{raw_path}' is not a file.")

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
        command = str(
            arguments.get(
                "command",
                "",
            )
        ).strip()

        if not command:
            return self._deny("run_shell requires a non-empty command.")

        # Git mutations belong to git_commit.
        if self._is_git_mutation(command):
            return self._deny("Do not use run_shell for Git mutations. Use git_commit.")

        # Obvious file creation/editing through shell belongs
        # to dedicated filesystem tools.
        if self._is_filesystem_write(command):
            return self._deny(
                "Do not use run_shell for direct file creation "
                "or editing when a dedicated filesystem tool exists. "
                "Use create_files or edit_file."
            )

        return ToolGuardDecision(
            allowed=True,
        )

    # =========================================================
    # GIT COMMIT
    # =========================================================

    def _check_git_commit(
        self,
        arguments: dict[str, Any],
        state: SessionState,
    ) -> ToolGuardDecision:
        user_task = self._latest_user_task(state)

        # No useful user text means don't overrule the model.
        if not user_task:
            return ToolGuardDecision(
                allowed=True,
            )

        requested_paths = self._extract_requested_paths(user_task)

        if not requested_paths:
            return ToolGuardDecision(
                allowed=True,
            )

        selected_paths = self._extract_commit_paths(arguments)

        all_changes = bool(
            arguments.get(
                "all_changes",
                False,
            )
        )

        # Explicit path request must not become
        # "commit everything".
        if all_changes:
            return self._deny(
                "The user requested a specific commit scope: "
                f"{', '.join(sorted(requested_paths))}. "
                "Do not commit all changes."
            )

        if selected_paths:
            unrelated = selected_paths - requested_paths

            missing = requested_paths - selected_paths

            if unrelated:
                return self._deny(
                    "Commit scope includes files the user did not request: "
                    + ", ".join(sorted(unrelated))
                )

            if missing:
                return self._deny(
                    "The user requested these files to be committed, "
                    "but they are missing from the commit scope: " + ", ".join(sorted(missing))
                )

        return ToolGuardDecision(
            allowed=True,
        )

    # =========================================================
    # HELPERS
    # =========================================================

    def _resolve(
        self,
        relative_path: str,
    ) -> Path:
        """
        Resolve through the same workspace root concept as
        the filesystem layer.

        The final tool still performs the authoritative path
        validation.
        """

        candidate = (self.workspace / relative_path).resolve()

        workspace = self.workspace.resolve()

        try:
            candidate.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {relative_path}") from exc

        return candidate

    @staticmethod
    def _is_git_mutation(
        command: str,
    ) -> bool:
        normalized = command.strip()

        return bool(
            re.search(
                r"(?i)"
                r"(?:^|[;&|])\s*"
                r"(?:git\s+)?"
                r"(?:add|commit|reset|restore|checkout|switch|clean)\b",
                normalized,
            )
        )

    @staticmethod
    def _is_filesystem_write(
        command: str,
    ) -> bool:
        """
        Detect common direct shell file mutations.

        This is intentionally conservative.
        We do NOT block package managers, compilers,
        test runners, scripts, or generators.
        """

        patterns = (
            # POSIX
            r"(?i)(?:^|[;&|])\s*(?:mkdir|touch)\b",
            r"(?i)(?:>|>>)\s*[^;&|]+",
            r"(?i)\becho\b.*(?:>|>>)",
            r"(?i)\bprintf\b.*(?:>|>>)",
            r"(?i)\bcat\b.*(?:>|>>)",
            r"(?i)\btee\b",
            # Windows / PowerShell
            r"(?i)\bNew-Item\b",
            r"(?i)\bSet-Content\b",
            r"(?i)\bAdd-Content\b",
            r"(?i)\bOut-File\b",
            r"(?i)\bmkdir\b",
        )

        return any(
            re.search(
                pattern,
                command,
            )
            for pattern in patterns
        )

    @staticmethod
    def _latest_user_task(
        state: SessionState,
    ) -> str:
        for message in reversed(state.messages):
            if message.get("role") != "user":
                continue

            content = message.get(
                "content",
                "",
            )

            if isinstance(
                content,
                str,
            ):
                text = content.strip()

                if text:
                    return text

        return ""

    @staticmethod
    def _extract_requested_paths(
        task: str,
    ) -> set[str]:
        """
        Extract obvious file/path references from a commit request.

        This intentionally avoids pretending that every natural
        language sentence can be parsed perfectly.
        """

        lowered = task.lower()

        commit_words = (
            "commit",
            "committed",
            "commit changes",
        )

        if not any(word in lowered for word in commit_words):
            return set()

        paths: set[str] = set()

        # Typical source/config paths.
        matches = re.findall(
            r"(?<![\w./-])"
            r"([A-Za-z0-9_.-]+"
            r"(?:/[A-Za-z0-9_.-]+)*"
            r"\.[A-Za-z0-9_-]+)"
            r"(?![\w./-])",
            task,
        )

        for match in matches:
            paths.add(
                match.replace(
                    "\\",
                    "/",
                )
            )

        # Directory names such as "commit evals".
        directory_matches = re.findall(
            r"\bcommit\s+"
            r"([A-Za-z0-9_.-]+)"
            r"(?:\s+only)?",
            task,
            flags=re.IGNORECASE,
        )

        for match in directory_matches:
            if "." not in match:
                paths.add(
                    match.replace(
                        "\\",
                        "/",
                    )
                )

        return paths

    @staticmethod
    def _extract_commit_paths(
        arguments: dict[str, Any],
    ) -> set[str]:
        paths: set[str] = set()

        raw_paths = arguments.get(
            "paths",
            [],
        )

        if isinstance(
            raw_paths,
            list,
        ):
            for item in raw_paths:
                if isinstance(
                    item,
                    str,
                ):
                    paths.add(
                        item.replace(
                            "\\",
                            "/",
                        )
                    )

        return paths

    @staticmethod
    def _deny(
        reason: str,
    ) -> ToolGuardDecision:
        return ToolGuardDecision(
            allowed=False,
            reason=reason,
        )
