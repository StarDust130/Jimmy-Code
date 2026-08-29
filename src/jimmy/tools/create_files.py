from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult


class CreateFileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(
        min_length=1,
        description="Workspace-relative path of the new file.",
    )

    content: str = Field(
        description="Complete UTF-8 text content for the new file.",
    )


class CreateFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[CreateFileSpec] = Field(
        min_length=1,
        description="Files to create.",
    )


class CreateFilesTool(Tool):
    """
    Create one or more new text files.

    Existing files are never overwritten.
    """

    def __init__(
        self,
        filesystem: Filesystem,
    ) -> None:
        self.filesystem = filesystem

    @property
    def name(self) -> str:
        return "create_files"

    @property
    def description(self) -> str:
        return (
            "Create one or more new UTF-8 text files inside the workspace. "
            "Parent directories are created automatically. "
            "Existing files are never overwritten. "
            "Use this instead of run_shell for creating source files, "
            "HTML, CSS, JavaScript, Python, configuration, tests, or similar files."
        )

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            read_only=False,
            destructive=False,
            requires_confirmation=False,
            timeout_seconds=15,
        )

    @property
    def input_model(self) -> type[BaseModel]:
        return CreateFilesInput

    def execute(
        self,
        arguments: BaseModel,
    ) -> ToolResult:
        args = CreateFilesInput.model_validate(arguments)

        if not args.files:
            raise ValueError("At least one file is required.")

        resolved: list[tuple[CreateFileSpec, Path]] = []

        seen: set[str] = set()

        for spec in args.files:
            relative = spec.path.strip()

            if not relative:
                raise ValueError("File path must not be empty.")

            normalized_key = relative.replace("\\", "/").lower()

            if normalized_key in seen:
                raise ValueError(f"Duplicate file path: {relative}")

            seen.add(normalized_key)

            path = self.filesystem.resolve_path(relative)

            if path.exists():
                raise FileExistsError(
                    f"File already exists: {relative}. Use edit_file to modify it."
                )

            resolved.append((spec, path))

        created: list[str] = []

        try:
            # Create all files only after validating all paths.
            for spec, path in resolved:
                path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                self._write_new_file(
                    path=path,
                    content=spec.content,
                )

                created.append(spec.path)

        except Exception:
            # Best-effort rollback for files created by THIS invocation.
            for relative in created:
                try:
                    created_path = self.filesystem.resolve_path(relative)
                    if created_path.exists() and created_path.is_file():
                        created_path.unlink()
                except OSError:
                    pass

            raise

        return ToolResult.ok(
            output=(
                f"Created {len(created)} file"
                f"{'' if len(created) == 1 else 's'}:\n"
                + "\n".join(f"- {path}" for path in created)
            ),
            metadata={
                "created": created,
                "count": len(created),
            },
        )

    @staticmethod
    def _write_new_file(
        path: Path,
        content: str,
    ) -> None:
        """
        Create the file without overwriting an existing file.

        Uses exclusive creation semantics to avoid accidental replacement.
        """

        try:
            with path.open(
                "x",
                encoding="utf-8",
                newline="",
            ) as handle:
                handle.write(content)

        except FileExistsError:
            raise

        except OSError as exc:
            raise OSError(f"Failed to create file '{path}': {exc}") from exc
