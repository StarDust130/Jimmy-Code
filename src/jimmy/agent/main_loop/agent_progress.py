from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

MAX_SAME_CALLS = 2


@dataclass
class AgentProgress:
    """
    Small guard against repeated actions that make no progress.

    This is intentionally simple:
    same tool + same arguments repeatedly
    -> block the useless repetition.

    A successful write/action resets the repetition state.
    """

    _counts: dict[str, int] = field(default_factory=dict)
    _blocked: set[str] = field(default_factory=set)

    @staticmethod
    def fingerprint(
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        normalized = json.dumps(
            arguments,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )

        return f"{tool_name}:{normalized}"

    def can_run(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[bool, str]:
        fingerprint = self.fingerprint(
            tool_name,
            arguments,
        )

        if fingerprint in self._blocked:
            return (
                False,
                "This exact tool action has already been "
                "blocked because it produced no progress. "
                "Choose a different action.",
            )

        count = self._counts.get(
            fingerprint,
            0,
        )

        if count >= MAX_SAME_CALLS:
            self._blocked.add(fingerprint)

            return (
                False,
                "This exact tool action was already "
                f"attempted {MAX_SAME_CALLS} times without "
                "enough progress. Do not repeat it.",
            )

        return True, ""

    def record(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        success: bool,
        changed_workspace: bool,
    ) -> None:
        fingerprint = self.fingerprint(
            tool_name,
            arguments,
        )

        if success and changed_workspace:
            # A real workspace change means the old action
            # may legitimately become useful again later.
            self._counts.clear()
            self._blocked.clear()
            return

        self._counts[fingerprint] = (
            self._counts.get(
                fingerprint,
                0,
            )
            + 1
        )

    def reset(self) -> None:
        self._counts.clear()
        self._blocked.clear()
