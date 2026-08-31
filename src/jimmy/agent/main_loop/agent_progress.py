from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# Only the exact same failed action is limited.
MAX_SAME_FAILED_ACTIONS = 2


@dataclass(slots=True)
class AgentProgress:
    """
    Tracks concrete execution progress for one task.

    This class intentionally does NOT understand:
    - natural language
    - user intent
    - task type
    - which tool should be used
    - whether a task is semantically complete

    It only records what actually happened.
    """

    _same_failed_actions: dict[str, int] = field(
        default_factory=dict,
    )

    _last_action: str | None = None

    _last_action_succeeded: bool | None = None

    _successful_tool_calls: int = 0

    _successful_mutations: int = 0

    # =========================================================
    # ACTION FINGERPRINT
    # =========================================================

    @staticmethod
    def fingerprint(
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """
        Build a stable fingerprint for an exact tool action.
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

    # =========================================================
    # BEFORE EXECUTION
    # =========================================================

    def can_run(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[bool, str]:
        """
        Prevent only repeated identical failed actions.
        """

        fingerprint = self.fingerprint(
            tool_name,
            arguments,
        )

        failures = self._same_failed_actions.get(
            fingerprint,
            0,
        )

        if failures >= MAX_SAME_FAILED_ACTIONS:
            return (
                False,
                (
                    "The exact same tool action has already "
                    f"failed {failures} times. "
                    "Do not repeat it unchanged. "
                    "Use a different or corrected approach."
                ),
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

        Tool-policy rejection is not execution and should
        therefore never call this method.
        """

        fingerprint = self.fingerprint(
            tool_name,
            arguments,
        )

        self._last_action = fingerprint

        self._last_action_succeeded = success

        if success:
            self._successful_tool_calls += 1

            self._same_failed_actions.pop(
                fingerprint,
                None,
            )

            if changed_workspace:
                self._successful_mutations += 1

                # Workspace progress makes previous failures
                # less useful.
                self._same_failed_actions.clear()

            return

        self._same_failed_actions[fingerprint] = (
            self._same_failed_actions.get(
                fingerprint,
                0,
            )
            + 1
        )

    # =========================================================
    # EVIDENCE
    # =========================================================

    @property
    def successful_tool_calls(self) -> int:
        return self._successful_tool_calls

    @property
    def successful_mutations(self) -> int:
        return self._successful_mutations

    @property
    def has_workspace_change(self) -> bool:
        return self._successful_mutations > 0

    @property
    def has_successful_tool_call(self) -> bool:
        return self._successful_tool_calls > 0

    # =========================================================
    # RESET
    # =========================================================

    def reset_after_progress(self) -> None:
        """
        Clear failure history after meaningful workspace progress.

        Do not clear successful-mutation evidence.
        """

        self._same_failed_actions.clear()

        self._last_action = None

        self._last_action_succeeded = None

    def reset(self) -> None:
        """
        Completely reset this task's progress state.
        """

        self._same_failed_actions.clear()

        self._last_action = None

        self._last_action_succeeded = None

        self._successful_tool_calls = 0

        self._successful_mutations = 0