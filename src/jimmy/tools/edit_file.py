from pydantic import BaseModel, ConfigDict

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult


class EditFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    old_text: str
    new_text: str


class EditFileTool(Tool):
    """Replace one exact text block in a text file."""

    def __init__(self, filesystem: Filesystem) -> None:
        self.filesystem = filesystem

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Replace one exact text block in a text file. The target text must exist exactly once."
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
        args = EditFileInput.model_validate(arguments)

        file_path = self.filesystem.resolve_path(args.path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {args.path}")

        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {args.path}")

        try:
            original = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"File is not valid UTF-8 text: {args.path}") from exc

        match_count = original.count(args.old_text)

        if match_count == 0:
            raise ValueError("The exact old_text was not found.")

        if match_count > 1:
            raise ValueError(
                f"The exact old_text matched "
                f"{match_count} times. "
                "Refusing to guess which occurrence to edit."
            )

        updated = original.replace(
            args.old_text,
            args.new_text,
            1,
        )

        if updated == original:
            raise ValueError("Edit produced no changes.")

        file_path.write_text(
            updated,
            encoding="utf-8",
        )

        return ToolResult.ok(
            output=f"Edited {args.path} successfully.",
            metadata={
                "path": args.path,
                "characters_before": len(original),
                "characters_after": len(updated),
            },
        )
