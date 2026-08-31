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
        description=(
            "Workspace-relative path for a NEW file. "
            "Include the complete path, including directories when needed, "
            "for example 'src/app/main.py' or 'mypkg/__init__.py'."
        ),
    )

    content: str = Field(
        description=(
            "Complete UTF-8 text content that should be written to the new file."
        ),
    )


class CreateFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[CreateFileSpec] = Field(
        min_length=1,
        description=(
            "One or more NEW files to create. "
            "Use one call for several independent new files when practical."
        ),
    )


class CreateFilesTool(Tool):
    """
    Create one or more new UTF-8 text files.

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
            "Create new UTF-8 text files inside the workspace. "
            "Use this when the target file does not already exist. "
            "Parent directories are created automatically. "
            "Existing files are never overwritten. "
            "For a multi-file feature, prefer creating all required NEW "
            "files in one call when their contents are already known. "
            "Use the exact workspace-relative paths requested by the user; "
            "for example, a Python package may require "
            "'mypkg/__init__.py' and 'mypkg/calculator.py'. "
            "Do not use this to modify an existing file; use edit_file instead. "
            "Do not use run_shell merely to write source files."
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

        resolved: list[tuple[CreateFileSpec, Path]] = []
        seen: set[str] = set()

        for spec in args.files:
            relative = spec.path.strip()

            if not relative:
                raise ValueError(
                    "File path must not be empty.",
                )

            normalized = relative.replace(
                "\\",
                "/",
            ).lower()

            if normalized in seen:
                raise ValueError(
                    f"Duplicate file path: {relative}",
                )

            seen.add(normalized)

            path = self.filesystem.resolve_path(
                relative,
            )

            if path.exists():
                raise FileExistsError(
                    f"File already exists: {relative}. "
                    "Use edit_file to modify it.",
                )

            resolved.append(
                (spec, path),
            )

        created: list[str] = []

        try:
            for spec, path in resolved:
                path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                self._write_new_file(
                    path=path,
                    content=spec.content,
                )

                created.append(
                    spec.path,
                )

        except Exception:
            for relative in created:
                try:
                    created_path = self.filesystem.resolve_path(
                        relative,
                    )

                    if (
                        created_path.exists()
                        and created_path.is_file()
                    ):
                        created_path.unlink()

                except OSError:
                    pass

            raise

        return ToolResult.ok(
            output=(
                f"Created {len(created)} file"
                f"{'' if len(created) == 1 else 's'}:\n"
                + "\n".join(
                    f"- {path}"
                    for path in created
                )
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
            raise OSError(
                f"Failed to create file '{path}': {exc}",
            ) from exc