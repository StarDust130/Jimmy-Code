from typing import Any

from jimmy.llm.base import LLMProvider

SUMMARY_PROMPT = """Summarize the following agent history.

Keep only information that is useful for continuing the coding task:
- important discoveries
- files inspected
- changes made
- test results
- failures
- unresolved issues

Be concise.
Do not invent facts.
"""


class ContextSummarizer:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    def summarize(
        self,
        messages: list[dict[str, Any]],
    ) -> str:
        history = "\n\n".join(
            f"{message.get('role')}: {message.get('content', '')}" for message in messages
        )

        response = self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": SUMMARY_PROMPT,
                },
                {
                    "role": "user",
                    "content": history,
                },
            ]
        )

        return response.content or ""
