import subprocess
from typing import Any

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem


class SearchFilesTool(Tool):
    """Search text across files in the working directory."""

    def __init__(self, filesystem: Filesystem) -> None:
        self.filesystem = filesystem

    @property
    def name(self) -> str:
        return "search_files"

    @property
    def description(self) -> str:
        return "Search for text or code patterns inside the working directory."

    def execute(self, arguments: dict[str, Any]) -> str:
        query = arguments.get("query")

        if not isinstance(query, str) or not query.strip():
            raise ValueError("'query' must be a non-empty string.")

        result = subprocess.run(
            [
                "rg",
                "--line-number",
                "--hidden",
                "--glob",
                "!.git",
                query,
                ".",
            ],
            cwd=self.filesystem.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

        if result.returncode == 1:
            return "No matches found."

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Search failed.")

        return result.stdout

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text or code pattern to search for.",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        }
