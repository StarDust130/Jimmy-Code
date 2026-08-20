from typing import Any

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem


class ReadFileTool(Tool):
    """Read a text file from the working directory."""

    def __init__(self, filesystem: Filesystem) -> None:
        self.filesystem = filesystem

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a text file inside the working directory."

    def execute(self, arguments: dict[str, Any]) -> str:
        path = arguments.get("path")

        if not isinstance(path, str) or not path.strip():
            raise ValueError("'path' must be a non-empty string.")

        file_path = self.filesystem.resolve_path(path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {path}")

        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"File is not valid UTF-8 text: {path}") from exc
