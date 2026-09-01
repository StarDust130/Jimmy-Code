import subprocess

from pydantic import BaseModel, ConfigDict

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult


class SearchFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str

    path: str | None = None


class SearchFilesTool(Tool):
    """Search text across files in the workspace."""

    def __init__(self, filesystem: Filesystem) -> None:
        self.filesystem = filesystem

    @property
    def name(self) -> str:
        return "search_files"

    @property
    def description(self) -> str:
        return (
            "Search text or code patterns. Set path to a known project folder "
            "to avoid searching unrelated parent-repository files."
        )

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

        search_root = "."
        if args.path is not None and args.path.strip():
            search_root = args.path.strip()
            path = self.filesystem.resolve_path(search_root)
            if not path.is_dir():
                raise FileNotFoundError(
                    f"Search path is not a directory: {search_root}"
                )

        # Models sometimes use '*' to mean "show me the files".  Passing it
        # to ripgrep as a regex produces a confusing parser failure and burns
        # another model turn.  Make that intent deterministic and read-only.
        if query in {"*", "."}:
            result = subprocess.run(
                ["rg", "--files", "--hidden", "--glob", "!.git", search_root],
                cwd=self.filesystem.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "File listing failed.")
            return ToolResult.ok(
                output=result.stdout or "No files found.",
                metadata={"query": query, "path": search_root, "exit_code": result.returncode},
            )

        result = subprocess.run(
            [
                "rg",
                "--line-number",
                "--hidden",
                "--glob",
                "!.git",
                query,
                search_root,
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
                    "path": search_root,
                    "exit_code": 1,
                },
            )

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Search failed.")

        return ToolResult.ok(
            output=result.stdout,
            metadata={
                "query": query,
                "path": search_root,
                "exit_code": result.returncode,
            },
        )
