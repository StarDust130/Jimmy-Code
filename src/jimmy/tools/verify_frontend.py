from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult


class VerifyFrontendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = Field(
        description="Workspace-relative directory containing a static HTML/CSS/JavaScript app."
    )


class VerifyFrontendTool(Tool):
    """Perform deterministic, offline checks for a static frontend app."""

    def __init__(self, filesystem: Filesystem) -> None:
        self.filesystem = filesystem

    @property
    def name(self) -> str:
        return "verify_frontend"

    @property
    def description(self) -> str:
        return (
            "Verify a static HTML/CSS/JavaScript folder without starting a server, "
            "using curl, Python, or network access. Checks linked local assets and "
            "JavaScript syntax when Node is available."
        )

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(read_only=True, destructive=False, requires_confirmation=False)

    @property
    def input_model(self) -> type[BaseModel]:
        return VerifyFrontendInput

    def execute(self, arguments: BaseModel) -> ToolResult:
        args = VerifyFrontendInput.model_validate(arguments)
        directory = self.filesystem.resolve_path(args.directory)
        if not directory.is_dir():
            raise FileNotFoundError(f"Frontend directory not found: {args.directory}")

        index = directory / "index.html"
        if not index.is_file():
            return ToolResult.fail("MissingIndex", "index.html is required for static frontend verification.")

        html = index.read_text(encoding="utf-8")
        references = re.findall(r"(?:src|href)=[\"']([^\"'#?]+)", html, flags=re.IGNORECASE)
        local_references = [
            reference
            for reference in references
            if not re.match(r"(?:https?:)?//", reference)
        ]
        missing = [reference for reference in local_references if not (directory / reference).is_file()]
        if missing:
            return ToolResult.fail("MissingAsset", "Missing local asset(s): " + ", ".join(missing))

        scripts = [directory / reference for reference in local_references if reference.lower().endswith(".js")]
        node = shutil.which("node")
        if node is not None:
            for script in scripts:
                result = subprocess.run(
                    [node, "--check", str(script)],
                    cwd=directory,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    timeout=15,
                )
                if result.returncode:
                    return ToolResult.fail("JavaScriptSyntaxError", result.stderr.strip() or f"Syntax check failed: {script.name}")

        details = ["index.html", *[script.name for script in scripts]]
        suffix = " (Node unavailable; asset checks only)" if node is None else ""
        return ToolResult.ok("Static frontend verified: " + ", ".join(details) + suffix)
