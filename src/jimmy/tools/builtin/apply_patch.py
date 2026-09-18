"""🩹 ApplyPatchTool — multi-hunk edits across files in ONE call."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..core.base import Tool, ToolResult


class PatchHunk(BaseModel):
    path: str = Field(description="File to edit.")
    search: str = Field(
        min_length=1,
        description="Exact existing text to find (include surrounding lines to disambiguate).",
    )
    replace: str = Field(description="Replacement text (may be empty to delete).")


class ApplyPatchArgs(BaseModel):
    patches: list[PatchHunk] = Field(
        min_length=1,
        description="ALL hunks to apply — batch every edit of this task here.",
    )


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = (
        "Apply MULTIPLE exact search/replace hunks across one or more "
        "files in a single call — much cheaper than calling edit_files "
        "repeatedly. Every `search` must match EXACTLY once in its file "
        "unless it is identical (idempotent). Best practice: read the "
        "file first, then send all hunks for it together."
    )
    args_schema = ApplyPatchArgs

    def execute(self, arguments: ApplyPatchArgs) -> ToolResult:
        workspace = Path.cwd().resolve()

        # 🗂️ group hunks per file → read each file once
        per_file: dict[str, list[PatchHunk]] = {}
        for hunk in arguments.patches:
            per_file.setdefault(hunk.path, []).append(hunk)

        applied: list[str] = []
        errors: list[str] = []

        for rel_path, hunks in per_file.items():
            path = (workspace / rel_path).resolve()

            try:
                path.relative_to(workspace)
            except ValueError:
                errors.append(f"{rel_path}: path is outside workspace")
                continue

            if not path.exists() or not path.is_file():
                errors.append(f"{rel_path}: file does not exist")
                continue

            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{rel_path}: cannot read: {exc}")
                continue

            working = content
            file_changed = 0

            for i, hunk in enumerate(hunks, start=1):
                count = working.count(hunk.search)

                if count == 0:
                    # 🟢 idempotent: already replaced before → skip quietly
                    if hunk.replace in working and hunk.search not in working:
                        continue
                    errors.append(f"{rel_path} hunk {i}: search text not found")
                    continue

                if count > 1:
                    errors.append(
                        f"{rel_path} hunk {i}: search matches {count} times — "
                        "add surrounding lines to make it unique"
                    )
                    continue

                working = working.replace(hunk.search, hunk.replace, 1)
                file_changed += 1

            if file_changed == 0:
                continue  # nothing applied for this file — don't rewrite

            try:
                path.write_text(working, encoding="utf-8")
            except OSError as exc:
                errors.append(f"{rel_path}: write failed: {exc}")
                continue

            applied.append(f"{rel_path} ({file_changed} hunk{'s' if file_changed != 1 else ''})")

        parts: list[str] = []
        if applied:
            parts.append("Changed:\n" + "\n".join(f"- {a}" for a in applied))
        if errors:
            parts.append("Errors:\n" + "\n".join(f"- {e}" for e in errors))

        if not applied and errors:
            return ToolResult(success=False, output="\n\n".join(parts) or "No changes.")

        return ToolResult(
            success=bool(applied) and not errors,
            output="\n\n".join(parts) or "No changes made.",
            error=None,
        )
