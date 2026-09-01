from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any


MAX_SAME_FAILED_ACTIONS = 2
MAX_RECENT_ACTIONS = 8
MAX_CHANGED_PATHS = 20
MAX_ACTION_DETAIL = 100


@dataclass(slots=True)
class AgentProgress:
    """
    Runtime progress for one task.

    Responsibilities:

    - prevent identical failed-action loops
    - record useful execution history
    - remember changed files
    - provide a compact progress checkpoint for the LLM

    This class does NOT:
    - plan the task
    - decide what the user wants
    - decide which tool to use
    - decide whether the task is complete
    """

    _same_failed_actions: dict[str, int] = field(
        default_factory=dict,
    )

    _successful_actions: dict[str, int] = field(
        default_factory=dict,
    )

    _tool_failure_streaks: dict[str, int] = field(
        default_factory=dict,
    )

    _last_action: str | None = None

    _last_action_succeeded: bool | None = None

    _successful_tool_calls: int = 0

    _successful_mutations: int = 0

    _total_tool_calls: int = 0

    _total_failures: int = 0

    _current_turn: int = 0

    _changed_paths: list[str] = field(
        default_factory=list,
    )

    _recent_actions: deque[str] = field(
        default_factory=lambda: deque(
            maxlen=MAX_RECENT_ACTIONS,
        ),
    )

    _last_error: str | None = None

    # =========================================================
    # ACTION ID
    # =========================================================

    @staticmethod
    def fingerprint(
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """
        Build a stable fingerprint for one exact action.
        """

        try:
            normalized = json.dumps(
                arguments,
                sort_keys=True,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            normalized = repr(
                sorted(
                    arguments.items(),
                    key=lambda item: item[0],
                ),
            )

        return f"{tool_name}:{normalized}"

    # =========================================================
    # TURN
    # =========================================================

    def start_turn(
        self,
        turn: int,
    ) -> None:
        """
        Record the current agent turn.

        This does not reset any progress.
        """

        if turn >= 0:
            self._current_turn = turn

    # =========================================================
    # BEFORE EXECUTION
    # =========================================================

    def can_run(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[bool, str]:
        """
        Allow normal retries while blocking the exact same
        failed action after the configured limit.
        """

        fingerprint = self.fingerprint(
            tool_name,
            arguments,
        )

        same_failures = self._same_failed_actions.get(
            fingerprint,
            0,
        )

        if same_failures >= MAX_SAME_FAILED_ACTIONS:
            return (
                False,
                (
                    "The exact same tool action has already "
                    f"failed {same_failures} times without progress. "
                    "Do not repeat it. Use a different approach."
                ),
            )

        # Reading the exact same file repeatedly is not useful progress.
        # Keep repeated shell commands allowed because polling/status checks
        # are legitimate, and clear this record after any workspace change.
        fingerprint = self.fingerprint(tool_name, arguments)
        if (
            tool_name == "read_file"
            and self._successful_actions.get(fingerprint, 0) >= 1
        ):
            return (
                False,
                "The same file was already read successfully. Use the existing result or choose a different target.",
            )

        return True, ""

    # =========================================================
    # AFTER EXECUTION
    # =========================================================

    def record(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        success: bool,
        changed_workspace: bool = False,
    ) -> None:
        """
        Record one actual tool execution.

        Existing callers remain compatible with the original API.
        """

        fingerprint = self.fingerprint(
            tool_name,
            arguments,
        )

        self._last_action = fingerprint

        self._last_action_succeeded = success

        self._total_tool_calls += 1

        self._add_recent_action(
            tool_name=tool_name,
            arguments=arguments,
            success=success,
        )

        # -----------------------------------------------------
        # SUCCESS
        # -----------------------------------------------------

        if success:
            self._successful_tool_calls += 1

            self._last_error = None

            self._same_failed_actions.pop(
                fingerprint,
                None,
            )

            self._successful_actions[fingerprint] = (
                self._successful_actions.get(fingerprint, 0) + 1
            )

            self._tool_failure_streaks.pop(
                tool_name,
                None,
            )

            if changed_workspace:
                self._successful_mutations += 1

                # A real edit can make an earlier failed action valid (for
                # example, fix code then rerun pytest). Only block loops
                # that have made no meaningful progress.
                self._same_failed_actions.clear()
                self._tool_failure_streaks.clear()
                self._successful_actions.clear()

                self._remember_changed_paths(
                    tool_name=tool_name,
                    arguments=arguments,
                )

            return

        # -----------------------------------------------------
        # FAILURE
        # -----------------------------------------------------

        self._total_failures += 1

        self._same_failed_actions[fingerprint] = (
            self._same_failed_actions.get(
                fingerprint,
                0,
            )
            + 1
        )

        self._tool_failure_streaks[tool_name] = (
            self._tool_failure_streaks.get(
                tool_name,
                0,
            )
            + 1
        )

        self._last_error = self._failure_detail(
            tool_name,
            arguments,
        )

    # =========================================================
    # RECENT ACTIONS
    # =========================================================

    def _add_recent_action(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        success: bool,
    ) -> None:
        symbol = "✓" if success else "✗"

        detail = self._action_detail(
            tool_name,
            arguments,
        )

        if detail:
            text = f"{symbol} {tool_name} {detail}"
        else:
            text = f"{symbol} {tool_name}"

        self._recent_actions.append(
            text[:MAX_ACTION_DETAIL],
        )

    @staticmethod
    def _action_detail(
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        if tool_name in {
            "read_file",
            "edit_file",
        }:
            path = arguments.get(
                "path",
            )

            if isinstance(
                path,
                str,
            ):
                return path

        if tool_name == "create_files":
            files = arguments.get(
                "files",
            )

            if isinstance(
                files,
                list,
            ):
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
                        paths.append(path)

                if paths:
                    return ", ".join(paths[:4])

        if tool_name == "git_commit":
            paths = arguments.get(
                "paths",
            )

            if isinstance(
                paths,
                list,
            ):
                values = [
                    path
                    for path in paths
                    if isinstance(
                        path,
                        str,
                    )
                ]

                if values:
                    return ", ".join(values[:4])

            return str(
                arguments.get(
                    "mode",
                    "",
                ),
            )

        if tool_name == "run_shell":
            command = arguments.get(
                "command",
            )

            if isinstance(
                command,
                str,
            ):
                command = " ".join(
                    command.split(),
                )

                if len(command) > MAX_ACTION_DETAIL:
                    command = (
                        command[
                            : MAX_ACTION_DETAIL - 1
                        ]
                        + "…"
                    )

                return command

        return ""

    @staticmethod
    def _failure_detail(
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        detail = AgentProgress._action_detail(
            tool_name,
            arguments,
        )

        if detail:
            return f"{tool_name} {detail}"

        return tool_name

    # =========================================================
    # CHANGED PATHS
    # =========================================================

    def _remember_changed_paths(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> None:
        paths: list[str] = []

        if tool_name in {
            "read_file",
            "edit_file",
        }:
            path = arguments.get(
                "path",
            )

            if isinstance(
                path,
                str,
            ):
                paths.append(path)

        elif tool_name == "create_files":
            files = arguments.get(
                "files",
            )

            if isinstance(
                files,
                list,
            ):
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
                        paths.append(path)

        elif tool_name == "git_commit":
            commit_paths = arguments.get(
                "paths",
            )

            if isinstance(
                commit_paths,
                list,
            ):
                for path in commit_paths:
                    if isinstance(
                        path,
                        str,
                    ):
                        paths.append(path)

        for path in paths:
            normalized = path.strip()

            if not normalized:
                continue

            if normalized in self._changed_paths:
                continue

            if len(
                self._changed_paths,
            ) >= MAX_CHANGED_PATHS:
                break

            self._changed_paths.append(
                normalized,
            )

    # =========================================================
    # CONTEXT
    # =========================================================

    def context_summary(
        self,
        *,
        max_chars: int = 2500,
    ) -> str:
        """
        Return a compact runtime checkpoint for the next
        model decision.

        This is transient context.
        It should NOT be persisted as a conversation message.
        """

        lines: list[str] = [
            "<task_progress>",
            (
                f"turn={self._current_turn} "
                f"tool_calls={self._total_tool_calls} "
                f"successful={self._successful_tool_calls} "
                f"failures={self._total_failures}"
            ),
            (
                f"successful_mutations="
                f"{self._successful_mutations}"
            ),
        ]

        if self._changed_paths:
            lines.append(
                "changed_files="
                + ", ".join(
                    self._changed_paths[:MAX_CHANGED_PATHS],
                ),
            )
        else:
            lines.append(
                "changed_files=none recorded",
            )

        if self._last_error:
            lines.append(
                "last_failure="
                + self._last_error[:300],
            )

        if self._recent_actions:
            lines.append(
                "recent_actions:",
            )

            lines.extend(
                f"- {action}"
                for action in self._recent_actions
            )

        lines.extend(
            [
                "Use this as execution state.",
                "Do not redo completed work.",
                "Continue the user's original task.",
                "</task_progress>",
            ],
        )

        result = "\n".join(lines)

        if len(result) <= max_chars:
            return result

        return (
            result[: max_chars - 30]
            + "\n[progress truncated]\n"
            + "</task_progress>"
        )

    # =========================================================
    # EXTERNAL STATE CHANGE
    # =========================================================

    def reset_after_progress(self) -> None:
        """
        Clear failure-loop history after meaningful external
        progress.

        Long-task history is intentionally preserved.
        """

        self._same_failed_actions.clear()

        self._tool_failure_streaks.clear()

        self._last_action = None

        self._last_action_succeeded = None

        self._last_error = None

    # =========================================================
    # RESET
    # =========================================================

    def reset(self) -> None:
        """
        Completely reset task progress.
        """

        self._same_failed_actions.clear()

        self._tool_failure_streaks.clear()

        self._last_action = None

        self._last_action_succeeded = None

        self._successful_tool_calls = 0

        self._successful_mutations = 0

        self._total_tool_calls = 0

        self._total_failures = 0

        self._current_turn = 0

        self._changed_paths.clear()

        self._recent_actions.clear()

        self._last_error = None
