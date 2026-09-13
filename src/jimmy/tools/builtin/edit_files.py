# src/jimmy/tools/builtin/edit_files.py

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from ..core.base import Tool, ToolResult


class FileEdit(BaseModel):
    # 1️⃣ File to edit
    path: str

    # 2️⃣ Preferred names for search/replace
    search: str | None = None
    replace: str | None = None

    # 3️⃣ Backward-compatible names
    old_text: str | None = None
    new_text: str | None = None

    # 4️⃣ Replace every match when true
    replace_all: bool = False

    @model_validator(mode="after")
    def normalize_names(self) -> "FileEdit":
        # 5️⃣ Use old names when new names are missing
        if self.search is None:
            self.search = self.old_text

        if self.replace is None:
            self.replace = self.new_text

        # 6️⃣ Both search and replace are required
        if self.search is None or self.replace is None:
            raise ValueError("Each edit requires search/replace (or old_text/new_text).")

        return self


class EditFilesArgs(BaseModel):
    # 7️⃣ Accept one or more edits
    edits: list[FileEdit] = Field(min_length=1)


class EditFilesTool(Tool):
    # 8️⃣ Tool name
    name = "edit_files"

    # 9️⃣ Tell the agent what this tool does
    description = (
        "Edit one or more text files by replacing exact text. "
        "Use search and replace for precise code changes."
    )

    # 🔟 Validate tool arguments
    args_schema = EditFilesArgs

    def execute(self, arguments: EditFilesArgs) -> ToolResult:
        # 1️⃣1️⃣ Use the current workspace
        workspace = Path.cwd().resolve()

        # 1️⃣2️⃣ Track successful edits
        changed: list[str] = []

        # 1️⃣3️⃣ Track failed edits
        errors: list[str] = []

        for edit in arguments.edits:
            # 1️⃣4️⃣ Build the full file path
            path = (workspace / edit.path).resolve()

            try:
                # 1️⃣5️⃣ Block paths outside the workspace
                path.relative_to(workspace)
            except ValueError:
                errors.append(f"{edit.path}: path is outside workspace")
                continue

            # 1️⃣6️⃣ File must exist
            if not path.exists():
                errors.append(f"{edit.path}: file does not exist")
                continue

            # 1️⃣7️⃣ Path must be a file
            if not path.is_file():
                errors.append(f"{edit.path}: not a file")
                continue

            try:
                # 1️⃣8️⃣ Read the original file
                original = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{edit.path}: cannot read file: {exc}")
                continue

            # 1️⃣9️⃣ Pydantic already validated these values
            assert edit.search is not None
            assert edit.replace is not None

            # 2️⃣0️⃣ Count how many matches exist
            count = original.count(edit.search)

            # 2️⃣1️⃣ Search text must exist
            if count == 0:
                errors.append(f"{edit.path}: search text was not found")
                continue

            # 2️⃣2️⃣ Avoid accidental multiple replacements
            if count > 1 and not edit.replace_all:
                errors.append(
                    f"{edit.path}: search text appears {count} times; "
                    "make it more specific or use replace_all=true"
                )
                continue

            # 2️⃣3️⃣ Apply the replacement
            if edit.replace_all:
                updated = original.replace(
                    edit.search,
                    edit.replace,
                )
            else:
                updated = original.replace(
                    edit.search,
                    edit.replace,
                    1,
                )

            try:
                # 2️⃣4️⃣ Save the changed file
                path.write_text(updated, encoding="utf-8")
            except OSError as exc:
                errors.append(f"{edit.path}: write failed: {exc}")
                continue

            # 2️⃣5️⃣ Record successful edit
            changed.append(edit.path)

        # 2️⃣6️⃣ Success only when all edits worked
        success = bool(changed) and not errors

        # 2️⃣7️⃣ Build the result
        output: list[str] = []

        if changed:
            output.append("Changed:\n" + "\n".join(f"- {path}" for path in changed))

        if errors:
            output.append("Errors:\n" + "\n".join(f"- {error}" for error in errors))

        # 2️⃣8️⃣ Return result to the agent
        return ToolResult(
            success=success,
            output="\n\n".join(output) or "No changes made.",
        )
