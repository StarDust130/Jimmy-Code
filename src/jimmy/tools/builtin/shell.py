from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from ..core.base import Tool, ToolResult


class ShellArgs(BaseModel):
    # 💻 Command to run
    command: str = Field(min_length=1)

    # ⏱️ Stop long-running commands
    timeout: int = Field(default=30, ge=1, le=300)


class ShellTool(Tool):
    # 🔧 Tool name
    name = "shell"

    # 📝 Tell the agent when to use it
    description = (
        "Run a shell command inside the current workspace. "
        "Use this for tests, builds, package commands, and other "
        "commands that do not have a more specific tool."
    )

    # 📋 Validate tool arguments
    args_schema = ShellArgs

    def execute(self, arguments: ShellArgs) -> ToolResult:
        # 📁 Run commands from the current workspace
        workspace = Path.cwd()

        try:
            # ▶️ Execute the command
            completed = subprocess.run(
                arguments.command,
                shell=True,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=arguments.timeout,
            )
        except subprocess.TimeoutExpired:
            # ⏱️ Command took too long
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Command timed out after "
                    f"{arguments.timeout} seconds."
                ),
            )
        except OSError as exc:
            # ⚠️ Failed to start command
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to run command: {exc}",
            )

        # 📤 Get command output
        output = completed.stdout

        # ⚠️ Include error output when present
        if completed.stderr:
            output += (
                "\n\n--- stderr ---\n"
                + completed.stderr
            )

        # ✅ Return command result
        return ToolResult(
            success=completed.returncode == 0,
            output=output.strip(),
            error=(
                f"Exit code: {completed.returncode}"
                if completed.returncode != 0
                else None
            ),
        )