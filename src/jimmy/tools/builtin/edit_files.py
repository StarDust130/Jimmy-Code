from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..core.base import Tool, ToolResult


class FileEdit(BaseModel):
    # 📍 File to change
    path: str

    # 🔎 Exact text to find
    old_text: str

    # ✏️ Replacement text
    new_text: str

    # 🔁 Replace every match when true
    replace_all: bool = False


class EditFilesArgs(BaseModel):
    # 📦 One or more file changes
    edits: list[FileEdit] = Field(min_length=1)


class EditFilesTool(Tool):
    # 🔧 Tool name
    name = "edit_files"

    # 📝 Tell the agent when to use it
    description = (
        "Edit one or more text files by replacing exact text. "
        "Use this for precise code changes."
    )

    # 📋 Validate tool arguments
    args_schema = EditFilesArgs

    def execute(self, arguments: EditFilesArgs) -> ToolResult:
        # 📁 Current workspace
        workspace = Path.cwd()

        # ✅ Track changed files
        changed: list[str] = []

        # ❌ Track errors
        errors: list[str] = []

        for edit in arguments.edits:
            # 📍 Build full file path
            path = (workspace / edit.path).resolve()

            try:
                # 🔒 Block paths outside workspace
                path.relative_to(workspace.resolve())
            except ValueError:
                errors.append(
                    f"{edit.path}: path is outside workspace"
                )
                continue

            # ❌ File not found
            if not path.exists():
                errors.append(f"{edit.path}: file does not exist")
                continue

            # ❌ Path is not a file
            if not path.is_file():
                errors.append(f"{edit.path}: not a file")
                continue

            try:
                # 📖 Read original file
                original = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                # ⚠️ Read failed
                errors.append(f"{edit.path}: cannot read file: {exc}")
                continue

            # 🔎 Make sure target text exists
            if edit.old_text not in original:
                errors.append(
                    f"{edit.path}: target text not found"
                )
                continue

            # 🔢 Count matching text
            occurrences = original.count(edit.old_text)

            # ⚠️ Avoid accidental multiple replacements
            if occurrences > 1 and not edit.replace_all:
                errors.append(
                    f"{edit.path}: target appears {occurrences} times; "
                    "set replace_all=true or make the match more specific"
                )
                continue

            # ✏️ Apply the replacement
            updated = (
                original.replace(edit.old_text, edit.new_text)
                if edit.replace_all
                else original.replace(edit.old_text, edit.new_text, 1)
            )

            try:
                # 💾 Save the updated file
                path.write_text(updated, encoding="utf-8")
            except OSError as exc:
                # ⚠️ Write failed
                errors.append(f"{edit.path}: write failed: {exc}")
                continue

            # ✅ Record successful edit
            changed.append(edit.path)

        # ✅ Only fully successful when all edits worked
        success = bool(changed) and not errors

        # 📦 Build result sections
        output_parts: list[str] = []

        if changed:
            output_parts.append(
                "Changed:\n" + "\n".join(f"- {path}" for path in changed)
            )

        if errors:
            output_parts.append(
                "Errors:\n" + "\n".join(f"- {error}" for error in errors)
            )

        # 📤 Return result to the agent
        return ToolResult(
            success=success,
            output="\n\n".join(output_parts) or "No changes made.",
        )