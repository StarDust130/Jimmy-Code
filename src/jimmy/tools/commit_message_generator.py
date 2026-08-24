import json
from dataclasses import dataclass

from jimmy.llm.base import LLMProvider


@dataclass(frozen=True)
class CommitChange:
    path: str
    diff: str


COMMIT_MESSAGE_PROMPT = """You generate Git commit messages for Jimmy.

Given changed files and their diffs, return ONE short commit message
for EACH file.

Rules:
- Return JSON only.
- Use exactly the provided file paths as keys.
- Keep each message very short: 3-7 words.
- Start with one useful emoji.
- Describe the actual change, not the filename alone.
- Do not invent changes.
- Prefer verbs such as add, fix, improve, refactor, update, remove, test.
- Do not use generic messages like "update file" or "change code".

Example:

{
  "src/auth.py": "🐛 fix token validation",
  "tests/test_auth.py": "🧪 add auth coverage"
}
"""


class CommitMessageGenerator:
    """Generates meaningful commit messages from Git diffs."""

    def __init__(
        self,
        llm: LLMProvider,
        max_files_per_batch: int = 20,
        max_chars_per_batch: int = 24_000,
        max_diff_chars_per_file: int = 4_000,
    ) -> None:
        self.llm = llm
        self.max_files_per_batch = max_files_per_batch
        self.max_chars_per_batch = max_chars_per_batch
        self.max_diff_chars_per_file = max_diff_chars_per_file

    def generate(
        self,
        changes: list[CommitChange],
    ) -> dict[str, str]:
        messages: dict[str, str] = {}

        for batch in self._batches(changes):
            messages.update(self._generate_batch(batch))

        return messages

    def _batches(
        self,
        changes: list[CommitChange],
    ) -> list[list[CommitChange]]:
        batches: list[list[CommitChange]] = []
        current: list[CommitChange] = []
        current_chars = 0

        for change in changes:
            diff = change.diff[: self.max_diff_chars_per_file]

            size = len(change.path) + len(diff)

            if current and (
                len(current) >= self.max_files_per_batch
                or current_chars + size > self.max_chars_per_batch
            ):
                batches.append(current)
                current = []
                current_chars = 0

            current.append(
                CommitChange(
                    path=change.path,
                    diff=diff,
                )
            )
            current_chars += size

        if current:
            batches.append(current)

        return batches

    def _generate_batch(
        self,
        batch: list[CommitChange],
    ) -> dict[str, str]:
        changes_text = "\n\n".join(f"FILE: {change.path}\nDIFF:\n{change.diff}" for change in batch)

        response = self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": COMMIT_MESSAGE_PROMPT,
                },
                {
                    "role": "user",
                    "content": changes_text,
                },
            ]
        )

        return self._parse_response(
            response.content or "",
            {change.path for change in batch},
        )

    @staticmethod
    def _parse_response(
        content: str,
        expected_paths: set[str],
    ) -> dict[str, str]:
        cleaned = content.strip()

        if cleaned.startswith("```"):
            lines = cleaned.splitlines()

            if lines and lines[0].startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            cleaned = "\n".join(lines).strip()

        data = json.loads(cleaned)

        if not isinstance(data, dict):
            raise TypeError("Commit message response must be a JSON object.")

        result: dict[str, str] = {}

        for path in expected_paths:
            message = data.get(path)

            if isinstance(message, str) and message.strip():
                result[path] = message.strip()

        return result
