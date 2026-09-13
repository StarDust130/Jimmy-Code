from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..core.base import Tool, ToolResult


# 🚫 Skip generated/dependency folders
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
}


class SearchFilesArgs(BaseModel):
    # 🔎 Text or filename to search
    query: str = Field(min_length=1)

    # 📁 Folder to search in
    path: str = "."

    # ✂️ Limit number of results
    max_results: int = Field(default=50, ge=1, le=200)


class SearchFilesTool(Tool):
    # 🔧 Tool name
    name = "search_files"

    # 📝 Tell the agent when to use it
    description = (
        "Search filenames and text inside the workspace. "
        "Use this to find relevant files or code before reading them."
    )

    # 📋 Validate tool arguments
    args_schema = SearchFilesArgs

    def execute(self, arguments: SearchFilesArgs) -> ToolResult:
        # 📁 Current workspace
        workspace = Path.cwd()

        # 📍 Search root
        root = (workspace / arguments.path).resolve()

        try:
            # 🔒 Block searches outside workspace
            root.relative_to(workspace.resolve())
        except ValueError:
            return ToolResult(
                success=False,
                output="",
                error="Search path is outside workspace.",
            )

        # ❌ Search path doesn't exist
        if not root.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Path does not exist: {arguments.path}",
            )

        # 🔡 Case-insensitive search
        query_lower = arguments.query.lower()

        # 📦 Store matches
        matches: list[str] = []

        # 🔍 Search all files recursively
        for path in root.rglob("*"):
            # 🛑 Stop after reaching the limit
            if len(matches) >= arguments.max_results:
                break

            # 📄 Only search files
            if not path.is_file():
                continue

            # 🚫 Skip ignored directories
            if any(part in IGNORED_DIRS for part in path.parts):
                continue

            relative = path.relative_to(workspace)

            # 🏷️ Check filename
            if query_lower in path.name.lower():
                matches.append(f"{relative}  [filename match]")
                continue

            try:
                # 📖 Read file for text search
                text = path.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )
            except OSError:
                # ⚠️ Skip unreadable files
                continue

            # 🔎 Find matching line
            for line_number, line in enumerate(text.splitlines(), start=1):
                if query_lower in line.lower():
                    snippet = line.strip()

                    # ✂️ Keep snippets small
                    if len(snippet) > 200:
                        snippet = snippet[:200] + "..."

                    matches.append(
                        f"{relative}:{line_number}: {snippet}"
                    )
                    break

        # 🔎 Nothing found
        if not matches:
            return ToolResult(
                success=True,
                output=f"No matches found for: {arguments.query}",
            )

        # ✂️ Results hit the limit
        truncated = len(matches) >= arguments.max_results

        # 📤 Format search results
        output = "\n".join(matches)

        if truncated:
            output += (
                f"\n\nShowing first {arguments.max_results} results."
            )

        # ✅ Return results to the agent
        return ToolResult(
            success=True,
            output=output,
        )