from pydantic import BaseModel, ConfigDict, Field

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult


class ReadFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="File path relative to the workspace.")

    line_start: int | None = Field(default=None, ge=1, description="First line to read, inclusive.")

    line_end: int | None = Field(default=None, ge=1, description="Last line to read, inclusive.")


class ReadFileTool(Tool):
    """Read a text file from the workspace."""

    def __init__(self, filesystem: Filesystem) -> None:
        self.filesystem = filesystem

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read the contents of a text file inside the current workspace."

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            read_only=True,
            destructive=False,
            requires_confirmation=False,
        )

    @property
    def input_model(self) -> type[BaseModel]:
        return ReadFileInput

    def execute(
        self,
        arguments: BaseModel,
    ) -> ToolResult:
        args = ReadFileInput.model_validate(arguments)

        if (
            args.line_start is not None
            and args.line_end is not None
            and args.line_end < args.line_start
        ):
            raise ValueError("'line_end' must be greater than or equal to 'line_start'.")

        file_path = self.filesystem.resolve_path(args.path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {args.path}")

        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {args.path}")

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"File is not valid UTF-8 text: {args.path}") from exc

        lines = content.splitlines()

        start = args.line_start - 1 if args.line_start is not None else 0

        end = args.line_end if args.line_end is not None else len(lines)

        content = "\n".join(lines[start:end])

        return ToolResult.ok(
            output=content,
            metadata={
                "path": args.path,
                "line_start": args.line_start,
                "line_end": args.line_end,
            },
        )
