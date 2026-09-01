from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jimmy.agent.task_state import TaskState
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
    Deterministic runtime policy guard.

    This guard does NOT:
    - choose tools
    - plan tasks
    - call the LLM
    - decide whether the task is complete
    - infer complex natural-language intent

    It only enforces hard runtime rules.
    """

    def __init__(
        self,
        workspace: Path,
    ) -> None:
        self.workspace = workspace.resolve()

    # =========================================================
    # PUBLIC
    # =========================================================

    def check(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        state: SessionState,
        task_state: TaskState | None = None,
    ) -> ToolGuardDecision:
        """
        Validate hard runtime rules.
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

        # -----------------------------------------------------
        # TASK-LEVEL BOUNDARIES
        # -----------------------------------------------------

        if task_state is not None:
            decision = self._check_task_scope(
                tool_name=tool_name,
                arguments=arguments,
                task_state=task_state,
            )

            if not decision.allowed:
                return decision

        # -----------------------------------------------------
        # TOOL-SPECIFIC VALIDATION
        # -----------------------------------------------------

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

        return ToolGuardDecision(
            allowed=True,
        )

    # =========================================================
    # TASK SCOPE
    # =========================================================

    def _check_task_scope(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        task_state: TaskState,
    ) -> ToolGuardDecision:
        """
        Enforce explicit user task boundaries.

        The model still decides what action to take.
        This guard only blocks actions that violate
        explicit boundaries.
        """

        # -----------------------------------------------------
        # GIT COMMIT
        # -----------------------------------------------------

        if tool_name == "git_commit":
            if not task_state.commit_requested:
                return self._deny(
                    "Git commit was not requested by the user.",
                )

            # No explicit file/path scope:
            #
            # Example:
            #   "Commit all changed files one by one."
            #
            # In this case the model/tool is allowed to determine
            # the complete commit set.
            if not task_state.requested_paths:
                return ToolGuardDecision(
                    allowed=True,
                )

            commit_paths = self._extract_commit_paths(
                arguments,
            )

            # When the user gave explicit scope, an omitted path
            # list is unsafe because it could mean "commit everything".
            if not commit_paths:
                return self._deny(
                    (
                        "This task has an explicit file scope. "
                        "git_commit must specify the requested path(s)."
                    ),
                )

            for path in commit_paths:
                if not task_state.is_path_in_scope(
                    path,
                ):
                    return self._deny(
                        (
                            f"Commit path '{path}' is outside "
                            "the explicit task scope."
                        ),
                    )

            return ToolGuardDecision(
                allowed=True,
            )

        # -----------------------------------------------------
        # FILE MUTATIONS
        # -----------------------------------------------------

        if tool_name in {
            "edit_file",
            "create_files",
        }:
            # No explicit scope means do not invent one.
            if not task_state.requested_paths:
                return ToolGuardDecision(
                    allowed=True,
                )

            paths = self._mutation_paths(
                tool_name=tool_name,
                arguments=arguments,
            )

            # Let the actual tool validate missing/invalid arguments.
            if not paths:
                return ToolGuardDecision(
                    allowed=True,
                )

            for path in paths:
                if not task_state.is_path_in_scope(
                    path,
                ):
                    return self._deny(
                        (
                            f"Path '{path}' is outside "
                            "the explicit scope of the current task."
                        ),
                    )

        return ToolGuardDecision(
            allowed=True,
        )

    # =========================================================
    # COMMIT PATHS
    # =========================================================

    @staticmethod
    def _extract_commit_paths(
        arguments: dict[str, Any],
    ) -> list[str]:
        """
        Extract explicit paths supplied to git_commit.

        Supported form:

            {
                "paths": ["main.py"]
            }
        """

        paths = arguments.get(
            "paths",
        )

        if paths is None:
            return []

        if not isinstance(
            paths,
            list,
        ):
            return []

        result: list[str] = []

        for path in paths:
            if isinstance(
                path,
                str,
            ) and path.strip():
                result.append(
                    path,
                )

        return result

    # =========================================================
    # MUTATION PATHS
    # =========================================================

    @staticmethod
    def _mutation_paths(
        tool_name: str,
        arguments: dict[str, Any],
    ) -> list[str]:
        """
        Extract file paths from mutation tool arguments.
        """

        if tool_name == "edit_file":
            path = arguments.get(
                "path",
            )

            if isinstance(
                path,
                str,
            ):
                return [path]

            return []

        if tool_name == "create_files":
            files = arguments.get(
                "files",
                [],
            )

            if not isinstance(
                files,
                list,
            ):
                return []

            paths: list[str] = []

            for item in files:
                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                path = item.get(
                    "path",
                )

                if isinstance(
                    path,
                    str,
                ):
                    paths.append(
                        path,
                    )

            return paths

        return []

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

        # Git mutations belong to the dedicated git_commit tool.
        #
        # Normal shell commands remain available for:
        # tests, builds, package managers, scripts, servers, etc.
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
                    (
                        f"'{raw_path}' already exists. "
                        "Use edit_file for existing files."
                    ),
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
                (
                    f"'{raw_path}' does not exist. "
                    "Use create_files for new files."
                ),
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
        candidate = (
            self.workspace / relative_path
        ).resolve()

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
                r"git\s+"
                r"(?:"
                r"add"
                r"|commit"
                r"|reset"
                r"|restore"
                r"|checkout"
                r"|switch"
                r"|clean"
                r"|rebase"
                r"|merge"
                r"|cherry-pick"
                r"|revert"
                r"|rm"
                r")\b",
                command,
            ),
        )

    # =========================================================
    # DENY
    # =========================================================

    @staticmethod
    def _deny(
        reason: str,
    ) -> ToolGuardDecision:
        return ToolGuardDecision(
            allowed=False,
            reason=reason,
        )