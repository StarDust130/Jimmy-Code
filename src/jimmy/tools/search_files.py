import subprocess

from pydantic import BaseModel, ConfigDict

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult


class SearchFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str


class SearchFilesTool(Tool):
    """Search text across files in the workspace."""

    def __init__(self, filesystem: Filesystem) -> None:
        self.filesystem = filesystem

    @property
    def name(self) -> str:
        return "search_files"

    @property
    def description(self) -> str:
        return "Search for text or code patterns inside the current workspace."

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            read_only=True,
            destructive=False,
            requires_confirmation=False,
            timeout_seconds=10,
        )

    @property
    def input_model(self) -> type[BaseModel]:
        return SearchFilesInput

    def execute(
        self,
        arguments: BaseModel,
    ) -> ToolResult:
        args = SearchFilesInput.model_validate(arguments)

        query = args.query.strip()

        if not query:
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
            check=False,
        )

        if result.returncode == 1:
            return ToolResult.ok(
                output="No matches found.",
                metadata={
                    "query": query,
                    "exit_code": 1,
                },
            )

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Search failed.")

        return ToolResult.ok(
            output=result.stdout,
            metadata={
                "query": query,
                "exit_code": result.returncode,
            },
        )
