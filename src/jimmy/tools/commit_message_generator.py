import json
from dataclasses import dataclass
from typing import Any

from jimmy.llm.base import LLMProvider


@dataclass(frozen=True)
class CommitChange:
    path: str
    diff: str


PER_FILE_PROMPT = """You write short, meaningful Git commit messages.

You receive real Git diffs for multiple files.

Return ONLY valid JSON.

Format:
{
  "path/to/file.py": "🧠 improve agent routing"
}

Rules:
- Use exactly the provided file paths as keys.
- Every provided file MUST have one message.
- Do not add extra keys.
- 3-8 words.
- Exactly one emoji at the beginning.
- Describe the actual change.
- Do not merely repeat the filename.
- Do not invent behavior.
- Use different messages for meaningfully different changes.

Emoji guide:
✨ new feature
🐛 bug fix
♻️ refactor
🧪 tests
⚡ performance
🔐 security
🎨 UI/style
📝 documentation
🧹 cleanup
🔧 configuration/integration
🏗️ architecture
📦 dependency
🔥 removal
🛠️ tooling
🚀 deployment
🧠 AI/agent/model behavior
🔌 API integration
🗂️ organization

Bad:
"🔧 update file.py"
"✨ change code"
"🛠️ update changes"
"🐛 fix bug"

Good:
"🏗️ split agent runtime"
"🧪 add planner tests"
"🐛 fix Windows path handling"
"🧠 improve tool routing"
"✂️ reduce context size"
"""


GROUP_PROMPT = """Write ONE short Git commit message for the following
collection of actual Git diffs.

Return ONLY valid JSON:

{
  "message": "🧠 improve agent architecture"
}

Rules:
- 3-8 words.
- Exactly one emoji at the beginning.
- Describe the main combined change.
- Use the actual diffs.
- Do not invent behavior.
- Do not use vague messages like "update files".
"""


class CommitMessageGenerator:
    """Generates useful commit messages from Git diffs."""

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

    def generate_per_file(
        self,
        changes: list[CommitChange],
    ) -> dict[str, str]:
        result: dict[str, str] = {}

        for batch in self._batches(changes):
            batch_result = self._generate_batch(batch)
            result.update(batch_result)

        return result

    def generate_group(
        self,
        changes: list[CommitChange],
    ) -> str:
        chunks: list[str] = []

        for change in changes:
            diff = change.diff[: self.max_diff_chars_per_file]

            chunks.append(f"FILE: {change.path}\nDIFF:\n{diff}")

        response = self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": GROUP_PROMPT,
                },
                {
                    "role": "user",
                    "content": "\n\n".join(chunks),
                },
            ],
        )

        return self._parse_group_response(
            response.content or "",
        )

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
        changes_text = "\n\n".join(
            (f"FILE: {change.path}\nDIFF:\n{change.diff}") for change in batch
        )

        response = self.llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": PER_FILE_PROMPT,
                },
                {
                    "role": "user",
                    "content": changes_text,
                },
            ],
        )

        return self._parse_per_file_response(
            response.content or "",
            expected_paths={change.path for change in batch},
        )

    @staticmethod
    def _clean_json(content: str) -> str:
        cleaned = content.strip()

        if cleaned.startswith("```"):
            lines = cleaned.splitlines()

            if lines and lines[0].startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            cleaned = "\n".join(lines).strip()

        return cleaned

    @classmethod
    def _parse_per_file_response(
        cls,
        content: str,
        expected_paths: set[str],
    ) -> dict[str, str]:
        data: Any = json.loads(
            cls._clean_json(content),
        )

        if not isinstance(data, dict):
            raise TypeError("Commit message response must be a JSON object.")

        if set(data) != expected_paths:
            raise ValueError(
                "Commit message response did not contain exactly the expected file paths."
            )

        result: dict[str, str] = {}

        for path in expected_paths:
            message = data[path]

            if not isinstance(message, str):
                raise TypeError(f"Commit message for {path} must be a string.")

            message = message.strip()

            if not message:
                raise ValueError(f"Empty commit message for {path}.")

            result[path] = message

        return result

    @classmethod
    def _parse_group_response(
        cls,
        content: str,
    ) -> str:
        data: Any = json.loads(
            cls._clean_json(content),
        )

        if not isinstance(data, dict):
            raise TypeError("Group commit message must be a JSON object.")

        message = data.get("message")

        if not isinstance(message, str):
            raise ValueError("Group commit message is missing.")

        message = message.strip()

        if not message:
            raise ValueError("Group commit message is empty.")

        return message
