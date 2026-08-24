from pydantic import BaseModel, ConfigDict

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult


class ReadFileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


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

        file_path = self.filesystem.resolve_path(args.path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {args.path}")

        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {args.path}")

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"File is not valid UTF-8 text: {args.path}") from exc

        return ToolResult.ok(
            output=content,
            metadata={
                "path": args.path,
            },
        )
