from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Same exact action failing repeatedly.
MAX_SAME_FAILURES = 2

# Same tool failing repeatedly, even with different arguments.
MAX_TOOL_FAILURE_STREAK = 3


@dataclass
class AgentProgress:
    """
    Small runtime guard against obvious no-progress loops.

    This is NOT a planner and NOT a task classifier.

    It only watches execution history:

        same exact failed action repeatedly
        OR
        same tool repeatedly failing

    Successful progress resets the failure state.

    Examples:

        edit_file -> success
        run_shell -> success
        run_shell -> fail
        run_shell -> fail
        run_shell -> fail
        -> stop repeating shell blindly

    But:

        edit_file -> success
        run_shell -> fail
        edit_file -> success
        run_shell -> fail

    remains allowed because the agent is still making progress.
    """

    _same_failures: dict[str, int] = field(
        default_factory=dict,
    )

    _tool_failure_streak: dict[str, int] = field(
        default_factory=dict,
    )

    @staticmethod
    def fingerprint(
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """
        Stable identity for one exact tool action.
        """

        normalized = json.dumps(
            arguments,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )

        return f"{tool_name}:{normalized}"

    def can_run(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[bool, str]:
        """
        Decide whether an action should be attempted again.
        """

        fingerprint = self.fingerprint(
            tool_name,
            arguments,
        )

        same_failures = self._same_failures.get(
            fingerprint,
            0,
        )

        if same_failures >= MAX_SAME_FAILURES:
            return (
                False,
                (
                    "The exact same tool action has already "
                    f"failed {same_failures} times. "
                    "Do not repeat it without a new approach."
                ),
            )

        tool_failures = self._tool_failure_streak.get(
            tool_name,
            0,
        )

        if tool_failures >= MAX_TOOL_FAILURE_STREAK:
            return (
                False,
                (
                    f"Tool '{tool_name}' has failed "
                    f"{tool_failures} times without successful "
                    "progress. Stop repeating it and use a "
                    "different approach."
                ),
            )

        return True, ""

    def record(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        success: bool,
        changed_workspace: bool,
        blocked: bool = False,
    ) -> None:
        """
        Record the actual execution outcome.

        blocked=True means the runtime rejected the action
        before the tool executed.
        """

        fingerprint = self.fingerprint(
            tool_name,
            arguments,
        )

        # -----------------------------------------------------
        # Guard/runtime rejection
        # -----------------------------------------------------

        if blocked:
            self._same_failures[fingerprint] = (
                self._same_failures.get(
                    fingerprint,
                    0,
                )
                + 1
            )

            self._tool_failure_streak[tool_name] = (
                self._tool_failure_streak.get(
                    tool_name,
                    0,
                )
                + 1
            )

            return

        # -----------------------------------------------------
        # Successful execution
        # -----------------------------------------------------

        if success:
            self._same_failures.pop(
                fingerprint,
                None,
            )

            self._tool_failure_streak.pop(
                tool_name,
                None,
            )

            # A successful workspace mutation is strong
            # evidence of real progress. Clear old failure
            # history because the task state has changed.
            if changed_workspace:
                self._same_failures.clear()
                self._tool_failure_streak.clear()

            return

        # -----------------------------------------------------
        # Tool executed but failed
        # -----------------------------------------------------

        self._same_failures[fingerprint] = (
            self._same_failures.get(
                fingerprint,
                0,
            )
            + 1
        )

        self._tool_failure_streak[tool_name] = (
            self._tool_failure_streak.get(
                tool_name,
                0,
            )
            + 1
        )

    def reset(self) -> None:
        """
        Reset all progress history.
        """

        self._same_failures.clear()
        self._tool_failure_streak.clear()
