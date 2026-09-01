"""
Context management layer:- 

SYSTEM RULES
CURRENT TASK
COMPACT SUMMARY OF OLDER WORK
LATEST IMPORTANT TOOL RESULTS
LATEST USER MESSAGE

SYSTEM
↓
previous work summary
↓
latest tool result
↓
latest edit
↓
latest test
↓
latest failure
↓
MODEL

"""


from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jimmy.context.context_summarizer import ContextSummarizer


@dataclass(frozen=True, slots=True)
class ContextConfig:
    """
    Limits for the LLM context.

    Hard limits:
        max_messages
        max_message_chars
        max_total_chars

    Compaction:
        Only happens when the context becomes large.
    """

    max_messages: int = 20
    max_message_chars: int = 8_000
    max_total_chars: int = 60_000

    compact_at_chars: int = 45_000

    # Approximate number of recent messages to preserve.
    # Tool-call + tool-result exchanges are always kept together.
    recent_messages: int = 8

    # Preserve the initial system messages.
    max_leading_system_messages: int = 2


class ContextManager:
    """
    Keeps LLM context bounded while preserving valid agent history.

    Important invariant:

        assistant(tool_calls)
        +
        tool(results)

    is treated as ONE atomic history block.

    This prevents context management from creating invalid
    function-calling conversations.
    """

    def __init__(
        self,
        summarizer: ContextSummarizer | None = None,
        config: ContextConfig | None = None,
    ) -> None:
        self.summarizer = summarizer
        self.config = config or ContextConfig()

        self._validate_config()

    # =========================================================
    # PUBLIC
    # =========================================================

    def prepare(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Prepare conversation history for an LLM request.

        Order:

            1. truncate oversized individual messages
            2. compact large contexts
            3. enforce message count
            4. enforce total context size

        Tool-call exchanges are never split.
        """

        normalized = self._truncate_messages(
            messages,
        )

        if (
            self._total_chars(normalized)
            >= self.config.compact_at_chars
        ):
            normalized = self._compact(
                normalized,
            )

        normalized = self._limit_message_count(
            normalized,
        )

        normalized = self._limit_total_size(
            normalized,
        )

        return normalized

    # =========================================================
    # CONFIG
    # =========================================================

    def _validate_config(
        self,
    ) -> None:
        if self.config.max_messages <= 0:
            raise ValueError(
                "max_messages must be greater than zero.",
            )

        if self.config.max_message_chars <= 0:
            raise ValueError(
                "max_message_chars must be greater than zero.",
            )

        if self.config.max_total_chars <= 0:
            raise ValueError(
                "max_total_chars must be greater than zero.",
            )

        if self.config.compact_at_chars <= 0:
            raise ValueError(
                "compact_at_chars must be greater than zero.",
            )

        if self.config.compact_at_chars > self.config.max_total_chars:
            raise ValueError(
                "compact_at_chars cannot exceed max_total_chars.",
            )

        if self.config.recent_messages < 0:
            raise ValueError(
                "recent_messages cannot be negative.",
            )

        if self.config.max_leading_system_messages < 0:
            raise ValueError(
                "max_leading_system_messages cannot be negative.",
            )

    # =========================================================
    # ATOMIC MESSAGE GROUPS
    # =========================================================

    @staticmethod
    def _group_messages(
        messages: list[dict[str, Any]],
    ) -> list[list[dict[str, Any]]]:
        """
        Group logically inseparable messages.

        A real user turn and the model/tool activity it caused:

            [user, assistant(tool_calls), tool, tool, ...]

        The group is never split by compaction or size trimming.
        """

        groups: list[list[dict[str, Any]]] = []

        index = 0

        while index < len(messages):
            message = messages[index]

            # -------------------------------------------------
            # User turns anchor all following model/tool messages until the
            # next user turn. Gemini requires function calls to follow a
            # real user or function-response turn, so compaction may never
            # retain a call exchange without its user anchor.
            # -------------------------------------------------

            if message.get("role") == "user":
                group = [message]

                index += 1

                while (
                    index < len(messages)
                    and messages[index].get("role") != "user"
                ):
                    next_message = messages[index]

                    group.append(
                        next_message,
                    )

                    index += 1

                groups.append(
                    group,
                )

                continue

            # -------------------------------------------------
            # Everything else is a single message.
            # -------------------------------------------------

            groups.append(
                [message],
            )

            index += 1

        return groups

    @staticmethod
    def _flatten_groups(
        groups: list[list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        return [
            message
            for group in groups
            for message in group
        ]

    @staticmethod
    def _group_chars(
        group: list[dict[str, Any]],
    ) -> int:
        return sum(
            ContextManager._message_chars(
                message,
            )
            for message in group
        )

    @staticmethod
    def _group_count(
        group: list[dict[str, Any]],
    ) -> int:
        return len(group)

    # =========================================================
    # COMPACTION
    # =========================================================

    def _compact(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Compact only old conversation history.

        Preserve:

            initial system messages
            +
            summary of old work
            +
            newest complete message groups
        """

        if self.summarizer is None:
            return messages

        leading = self._leading_system_messages(
            messages,
        )

        leading_count = len(leading)

        remaining = messages[
            leading_count:
        ]

        if not remaining:
            return messages

        groups = self._group_messages(
            remaining,
        )

        if not groups:
            return messages

        recent_groups = self._take_recent_groups(
            groups,
            self.config.recent_messages,
        )

        recent_group_count = len(
            recent_groups,
        )

        if recent_group_count >= len(groups):
            return messages

        old_groups = groups[
            : len(groups) - recent_group_count
        ]

        old_messages = self._flatten_groups(
            old_groups,
        )

        recent_messages = self._flatten_groups(
            recent_groups,
        )

        if not old_messages:
            return messages

        summary = self._summarize(
            old_messages,
        )

        if not summary:
            # Never destroy useful context because summarization failed.
            return messages

        return [
            *leading,
            {
                "role": "system",
                "content": (
                    "Previous work summary:\n"
                    f"{summary}"
                ),
            },
            *recent_messages,
        ]

    def _summarize(
        self,
        messages: list[dict[str, Any]],
    ) -> str:
        if (
            self.summarizer is None
            or not messages
        ):
            return ""

        try:
            summary = self.summarizer.summarize(
                messages,
            )
        except Exception:
            return ""

        if not isinstance(
            summary,
            str,
        ):
            return ""

        return summary.strip()

    @staticmethod
    def _take_recent_groups(
        groups: list[list[dict[str, Any]]],
        target_messages: int,
    ) -> list[list[dict[str, Any]]]:
        """
        Take complete groups from newest to oldest.

        Never split a tool-call group.

        At least one group is preserved when groups exist.
        """

        if not groups:
            return []

        if target_messages <= 0:
            return [
                groups[-1],
            ]

        selected: list[list[dict[str, Any]]] = []
        count = 0

        for group in reversed(groups):
            selected.append(
                group,
            )

            count += len(group)

            if count >= target_messages:
                break

        selected.reverse()

        return selected

    # =========================================================
    # MESSAGE COUNT
    # =========================================================

    def _limit_message_count(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Enforce max_messages without splitting tool exchanges.
        """

        if len(messages) <= self.config.max_messages:
            return messages

        leading = self._leading_system_messages(
            messages,
        )

        leading_ids = {
            id(message)
            for message in leading
        }

        remaining = [
            message
            for message in messages
            if id(message) not in leading_ids
        ]

        groups = self._group_messages(
            remaining,
        )

        available = (
            self.config.max_messages
            - len(leading)
        )

        if available <= 0:
            return leading[
                : self.config.max_messages
            ]

        selected_reversed: list[list[dict[str, Any]]] = []
        used = 0

        for group in reversed(groups):
            group_size = len(group)

            # Preserve an atomic group even when it itself is larger
            # than the remaining limit. Invalid history is worse than
            # a soft count overflow.
            if (
                not selected_reversed
                and group_size > available
            ):
                selected_reversed.append(
                    group,
                )
                used += group_size
                break

            if used + group_size > available:
                continue

            selected_reversed.append(
                group,
            )

            used += group_size

            if used >= available:
                break

        selected_reversed.reverse()

        selected = self._flatten_groups(
            selected_reversed,
        )

        result = [
            *leading,
            *selected,
        ]

        return result

    # =========================================================
    # INDIVIDUAL MESSAGE SIZE
    # =========================================================

    def _truncate_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Bound each individual message.

        Metadata is preserved.
        """

        result: list[dict[str, Any]] = []

        for message in messages:
            normalized = dict(
                message,
            )

            content = normalized.get(
                "content",
                "",
            )

            if not isinstance(
                content,
                str,
            ):
                content = str(
                    content,
                )

            if len(content) > self.config.max_message_chars:
                content = (
                    content[: self.config.max_message_chars]
                    + "\n\n[message truncated]"
                )

            normalized["content"] = content

            result.append(
                normalized,
            )

        return result

    # =========================================================
    # TOTAL SIZE
    # =========================================================

    def _limit_total_size(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Enforce max_total_chars while preserving complete
        tool-call exchanges.

        We prefer:

            system messages
            +
            newest complete groups
        """

        if (
            self._total_chars(messages)
            <= self.config.max_total_chars
        ):
            return messages

        leading = self._leading_system_messages(
            messages,
        )

        leading_ids = {
            id(message)
            for message in leading
        }

        remaining = [
            message
            for message in messages
            if id(message) not in leading_ids
        ]

        groups = self._group_messages(
            remaining,
        )

        selected_reversed: list[list[dict[str, Any]]] = []

        total = sum(
            self._message_chars(message)
            for message in leading
        )

        # -----------------------------------------------------
        # Newest groups have highest value.
        # -----------------------------------------------------

        for group in reversed(groups):
            group_size = self._group_chars(
                group,
            )

            if total + group_size <= self.config.max_total_chars:
                selected_reversed.append(
                    group,
                )

                total += group_size

                continue

            # If nothing has been selected yet and the newest
            # group itself exceeds the remaining budget, preserve
            # the complete group rather than breaking the
            # function-call protocol.
            if not selected_reversed:
                selected_reversed.append(
                    group,
                )

                total += group_size

                break

        selected_reversed.reverse()

        selected = self._flatten_groups(
            selected_reversed,
        )

        return [
            *leading,
            *selected,
        ]

    # =========================================================
    # SYSTEM MESSAGES
    # =========================================================

    def _leading_system_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Preserve the initial system instructions.
        """

        result: list[dict[str, Any]] = []

        for message in messages:
            if message.get("role") != "system":
                break

            result.append(
                message,
            )

            if len(result) >= (
                self.config.max_leading_system_messages
            ):
                break

        return result

    # =========================================================
    # SIZE HELPERS
    # =========================================================

    @staticmethod
    def _message_chars(
        message: dict[str, Any],
    ) -> int:
        return len(
            str(
                message.get(
                    "content",
                    "",
                ),
            ),
        )

    @staticmethod
    def _total_chars(
        messages: list[dict[str, Any]],
    ) -> int:
        return sum(
            ContextManager._message_chars(
                message,
            )
            for message in messages
        )
