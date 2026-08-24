from dataclasses import dataclass
from typing import Any

from jimmy.context.context_summarizer import ContextSummarizer


@dataclass
class ContextConfig:
    max_messages: int = 20
    max_message_chars: int = 8_000
    max_total_chars: int = 60_000
    compact_at_chars: int = 45_000


class ContextManager:
    """Keeps agent context bounded and compact."""

    def __init__(
        self,
        summarizer: ContextSummarizer | None = None,
        config: ContextConfig | None = None,
    ) -> None:
        self.summarizer = summarizer
        self.config = config or ContextConfig()

    def prepare(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        messages = self._truncate_messages(messages)

        if self._total_chars(messages) >= self.config.compact_at_chars:
            messages = self._compact(messages)

        messages = self._limit_message_count(messages)
        messages = self._limit_total_size(messages)

        return messages

    def _compact(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self.summarizer is None or len(messages) <= 4:
            return messages

        old_messages = messages[2:-4]
        recent_messages = messages[-4:]

        summary = self.summarizer.summarize(old_messages)

        return [
            *messages[:2],
            {
                "role": "system",
                "content": (f"Compacted prior context:\n{summary}"),
            },
            *recent_messages,
        ]

    def _truncate_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        for message in messages:
            content = str(message.get("content", ""))

            if len(content) > self.config.max_message_chars:
                content = content[: self.config.max_message_chars] + "\n\n[message truncated]"

            result.append(
                {
                    **message,
                    "content": content,
                }
            )

        return result

    def _limit_message_count(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if len(messages) <= self.config.max_messages:
            return messages

        important = messages[:2]
        recent = messages[-(self.config.max_messages - 2) :]

        return important + recent

    def _limit_total_size(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        total = 0
        result = []

        for message in messages:
            size = len(str(message.get("content", "")))

            if total + size > self.config.max_total_chars:
                break

            result.append(message)
            total += size

        return result

    @staticmethod
    def _total_chars(
        messages: list[dict[str, Any]],
    ) -> int:
        return sum(len(str(message.get("content", ""))) for message in messages)
