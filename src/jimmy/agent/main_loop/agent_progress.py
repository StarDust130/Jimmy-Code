from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Conservative limits.
#
# We do NOT want to block a legitimate retry too early.
MAX_SAME_FAILED_ACTIONS = 2


@dataclass(slots=True)
class AgentProgress:
    """
    Lightweight runtime guard against obvious no-progress loops.

    This class does not understand user language and does not
    decide which tool should be used.

    It only tracks what actually happened during execution.

    A retry is allowed when:
        - the action is different
        - the tool/environment has changed
        - the previous attempt succeeded
        - the previous failure has not reached the limit

    A repeated identical failure is eventually blocked.
    """

    _same_failed_actions: dict[str, int] = field(
        default_factory=dict,
    )

    _tool_failure_streaks: dict[str, int] = field(
        default_factory=dict,
    )

    _last_action: str | None = None
    _last_action_succeeded: bool | None = None

    # ---------------------------------------------------------
    # ACTION ID
    # ---------------------------------------------------------

    @staticmethod
    def fingerprint(
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """
        Build a stable ID for one exact tool action.

        Example:

            edit_file(path="a.py", old_text="x", new_text="y")

        always produces the same fingerprint.
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
                )
            )

        return f"{tool_name}:{normalized}"

    # ---------------------------------------------------------
    # BEFORE EXECUTION
    # ---------------------------------------------------------

    def can_run(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[bool, str]:
        """
        Decide whether the exact action should be attempted.

        This only blocks actions that have repeatedly failed.
        Successful actions are never blocked by this method.
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

        return True, ""

    # ---------------------------------------------------------
    # AFTER EXECUTION
    # ---------------------------------------------------------

    def record(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        success: bool,
        changed_workspace: bool = False,
    ) -> None:
        """
        Record one real tool execution.

        IMPORTANT:

        Only actual execution reaches this method.

        A tool-choice rejection should NOT be recorded here.
        """

        fingerprint = self.fingerprint(
            tool_name,
            arguments,
        )

        self._last_action = fingerprint
        self._last_action_succeeded = success

        # -----------------------------------------------------
        # Successful execution
        # -----------------------------------------------------

        if success:
            self._same_failed_actions.pop(
                fingerprint,
                None,
            )

            self._tool_failure_streaks.pop(
                tool_name,
                None,
            )

            # A successful workspace mutation means the world
            # has changed. Old failures are no longer useful.
            if changed_workspace:
                self._same_failed_actions.clear()
                self._tool_failure_streaks.clear()

            return

        # -----------------------------------------------------
        # Failed execution
        # -----------------------------------------------------

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

    # ---------------------------------------------------------
    # EXTERNAL STATE CHANGE
    # ---------------------------------------------------------

    def reset_after_progress(self) -> None:
        """
        Clear failure history after meaningful external progress.

        Useful when another subsystem knows that the workspace
        or execution environment changed.
        """

        self._same_failed_actions.clear()
        self._tool_failure_streaks.clear()

        self._last_action = None
        self._last_action_succeeded = None

    # ---------------------------------------------------------
    # RESET
    # ---------------------------------------------------------

    def reset(self) -> None:
        self.reset_after_progress()
