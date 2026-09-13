from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..core.base import Tool, ToolResult


class ReadFilesArgs(BaseModel):
    # 📥 Files to read
    paths: list[str] = Field(min_length=1)

    # ✂️ Limit output per file
    max_chars_per_file: int = Field(default=20_000, ge=1, le=100_000)


class ReadFilesTool(Tool):
    # 🔧 Tool name
    name = "read_files"

    # 📝 Tell the agent what this tool does
    description = (
        "Read one or more text files from the current workspace. "
        "Use this when you need to inspect file contents."
    )

    # 📋 Validate tool arguments
    args_schema = ReadFilesArgs

    def execute(self, arguments: ReadFilesArgs) -> ToolResult:
        # 📁 Current project folder
        workspace = Path.cwd()

        # 📦 Store each file result
        results: list[str] = []

        for raw_path in arguments.paths:
            # 📍 Build full file path
            path = (workspace / raw_path).resolve()

            try:
                # 🔒 Block paths outside the workspace
                path.relative_to(workspace.resolve())
            except ValueError:
                results.append(f"{raw_path}: ERROR path is outside workspace")
                continue

            # ❌ File not found
            if not path.exists():
                results.append(f"{raw_path}: ERROR file does not exist")
                continue

            # ❌ Not a file
            if not path.is_file():
                results.append(f"{raw_path}: ERROR not a file")
                continue

            try:
                # 📖 Read file contents
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                # 🚫 Binary/non-text file
                results.append(f"{raw_path}: ERROR binary/non-text file")
                continue
            except OSError as exc:
                # ⚠️ File system error
                results.append(f"{raw_path}: ERROR {exc}")
                continue

            # ✂️ Cut large files to save tokens/context
            truncated = len(text) > arguments.max_chars_per_file

            if truncated:
                text = text[: arguments.max_chars_per_file]

            # ℹ️ Tell the agent content was cut
            suffix = "\n...[truncated]" if truncated else ""

            results.append(
                f"===== {raw_path} =====\n"
                f"{text}{suffix}"
            )

        # ✅ Success if at least one file worked
        success = any(
            "ERROR" not in result.splitlines()[0]
            for result in results
        )

        # 📤 Return results to the agent
        return ToolResult(
            success=success,
            output="\n\n".join(results),
        )