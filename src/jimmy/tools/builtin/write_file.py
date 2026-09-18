"""✍️ WriteFileTool — create new files (or fully rewrite one)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..core.base import Tool, ToolResult


class WriteFileArgs(BaseModel):
    path: str = Field(description="File to create/rewrite (relative to workspace).")
    content: str = Field(
        default="",
        description="Full file content. Empty string creates an empty file.",
    )
    overwrite: bool = Field(
        default=False,
        description=(
            "Allow overwriting an EXISTING file. False (default) refuses "
            "to clobber — use edit_files for modifying existing files."
        ),
    )


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Create a NEW file with the given content (creates parent folders "
        "automatically). Refuses to overwrite an existing file unless "
        "overwrite=true. Do NOT use it to modify existing files — use "
        "edit_files for precise replacements, shell for mkdir-only needs."
    )
    args_schema = WriteFileArgs

    def execute(self, arguments: WriteFileArgs) -> ToolResult:
        workspace = Path.cwd().resolve()
        path = (workspace / arguments.path).resolve()

        # 🔒 workspace guard
        try:
            path.relative_to(workspace)
        except ValueError:
            return ToolResult(
                success=False,
                output="",
                error=f"Path is outside workspace: {arguments.path}",
            )

        existed = path.exists()

        if existed and path.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Path is a directory, not a file: {arguments.path}",
            )

        if existed and not arguments.overwrite:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"{arguments.path} already exists — pass overwrite=true "
                    "to replace it, or use edit_files to modify it."
                ),
            )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(arguments.content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Write failed: {exc}",
            )

        verb = "Rewrote" if existed else "Created"
        size_note = f" ({len(arguments.content)} chars)"

        return ToolResult(
            success=True,
            output=f"{verb}: {arguments.path}{size_note}",
        )
