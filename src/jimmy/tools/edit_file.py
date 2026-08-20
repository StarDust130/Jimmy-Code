from typing import Any

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem


class EditFileTool(Tool):
    """Replace one exact text block in a text file."""

    def __init__(self, filesystem: Filesystem) -> None:
        self.filesystem = filesystem

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return "Replace one exact text block in a text file. The old text must exist exactly once."

    def execute(self, arguments: dict[str, Any]) -> str:
        path = arguments.get("path")
        old_text = arguments.get("old_text")
        new_text = arguments.get("new_text")

        if not isinstance(path, str) or not path.strip():
            raise ValueError("'path' must be a non-empty string.")

        if not isinstance(old_text, str) or not old_text:
            raise ValueError("'old_text' must be a non-empty string.")

        if not isinstance(new_text, str):
            raise ValueError("'new_text' must be a string.")

        file_path = self.filesystem.resolve_path(path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {path}")

        try:
            original = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"File is not valid UTF-8 text: {path}") from exc

        match_count = original.count(old_text)

        if match_count == 0:
            raise ValueError("The exact old_text was not found in the file.")

        if match_count > 1:
            raise ValueError(
                f"The exact old_text matched {match_count} times. "
                "Refuse to guess which occurrence to edit."
            )

        updated = original.replace(old_text, new_text, 1)

        if updated == original:
            raise ValueError("Edit produced no changes.")

        file_path.write_text(updated, encoding="utf-8")

        return f"Edited {path} successfully.\nCharacters changed: {len(original)} -> {len(updated)}"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file relative to the working directory.",
                },
                "old_text": {
                    "type": "string",
                    "description": "Exact existing text to replace.",
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text.",
                },
            },
            "required": ["path", "old_text", "new_text"],
            "additionalProperties": False,
        }
