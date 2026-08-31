from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult


class EditFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        min_length=1,
        description=(
            "Workspace-relative path of an EXISTING text file."
        ),
    )

    old_text: str = Field(
        description=(
            "Exact existing text block to replace. "
            "It must match exactly once."
        ),
    )

    new_text: str = Field(
        description=(
            "Complete replacement text for the matched block."
        ),
    )


class EditFileTool(Tool):
    """
    Modify one existing UTF-8 text file using an exact replacement.
    """

    def __init__(
        self,
        filesystem: Filesystem,
    ) -> None:
        self.filesystem = filesystem

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Modify an EXISTING UTF-8 text file by replacing one exact "
            "text block. "
            "Use this for code changes, bug fixes, refactors, styling, "
            "and other edits to files that already exist. "
            "old_text must match exactly once; if it does not, inspect "
            "the current file and choose a better edit instead of guessing. "
            "For a NEW file, use create_files. "
            "Do not recreate or overwrite an existing file with create_files. "
            "For a larger feature, make coherent changes to the affected "
            "existing files rather than unrelated files."
        )

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            read_only=False,
            destructive=False,
            requires_confirmation=False,
            timeout_seconds=10,
        )

    @property
    def input_model(self) -> type[BaseModel]:
        return EditFileInput

    def execute(
        self,
        arguments: BaseModel,
    ) -> ToolResult:
        args = EditFileInput.model_validate(
            arguments,
        )

        path = self.filesystem.resolve_path(
            args.path,
        )

        if not path.exists():
            raise FileNotFoundError(
                f"File not found: {args.path}. "
                "Use create_files to create a new file.",
            )

        if not path.is_file():
            raise ValueError(
                f"Path is not a file: {args.path}",
            )

        try:
            original = path.read_text(
                encoding="utf-8",
            )
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"File is not valid UTF-8 text: {args.path}",
            ) from exc
        except OSError as exc:
            raise OSError(
                f"Failed to read file '{args.path}': {exc}",
            ) from exc

        if not args.old_text:
            raise ValueError(
                "'old_text' must not be empty.",
            )

        match_count = original.count(
            args.old_text,
        )

        if match_count == 0:
            raise ValueError(
                "The exact old_text was not found. "
                "Read the current file and retry with the exact text.",
            )

        if match_count > 1:
            raise ValueError(
                f"The exact old_text matched {match_count} times. "
                "Refusing to guess which occurrence to edit.",
            )

        updated = original.replace(
            args.old_text,
            args.new_text,
            1,
        )

        if updated == original:
            raise ValueError(
                "Edit produced no changes.",
            )

        try:
            path.write_text(
                updated,
                encoding="utf-8",
            )
        except OSError as exc:
            raise OSError(
                f"Failed to write file '{args.path}': {exc}",
            ) from exc

        return ToolResult.ok(
            output=(
                f"Edited {args.path} successfully."
            ),
            metadata={
                "path": args.path,
                "changed": True,
                "characters_before": len(original),
                "characters_after": len(updated),
            },
        )