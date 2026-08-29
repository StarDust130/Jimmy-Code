from __future__ import annotations

import subprocess
from typing import Final

from pydantic import BaseModel, ConfigDict

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult
from jimmy.utils.safety import check_shell_command

DEFAULT_TIMEOUT: Final[int] = 120
MAX_TIMEOUT: Final[int] = 600


class RunShellInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str


class RunShellTool(Tool):
    """
    Execute a real shell command inside the workspace.

    This tool is intentionally for commands/program execution.
    Use dedicated filesystem tools for creating or editing files.
    """

    def __init__(
        self,
        filesystem: Filesystem,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero.")

        self.filesystem = filesystem
        self.timeout = min(timeout, MAX_TIMEOUT)

    @property
    def name(self) -> str:
        return "run_shell"

    @property
    def description(self) -> str:
        return (
            "Run a shell command inside the current workspace. "
            "Use this for tests, builds, linters, scripts, package commands, "
            "program execution, and other commands that genuinely require a shell. "
            "Do NOT use this to create, edit, delete, move, or rename files when "
            "a dedicated filesystem tool exists. "
            "For Git commits, always use git_commit instead of git add/git commit."
        )

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            read_only=False,
            destructive=True,
            requires_confirmation=True,
            timeout_seconds=float(self.timeout),
        )

    @property
    def input_model(self) -> type[BaseModel]:
        return RunShellInput

    def execute(
        self,
        arguments: BaseModel,
    ) -> ToolResult:
        args = RunShellInput.model_validate(arguments)

        command = args.command.strip()

        if not command:
            raise ValueError("'command' must be a non-empty string.")

        check_shell_command(command)

        try:
            completed = subprocess.run(
                command,
                cwd=self.filesystem.root,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )

        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"Command timed out after {self.timeout} seconds.") from exc

        except OSError as exc:
            raise RuntimeError(f"Failed to start shell command: {exc}") from exc

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()

        metadata = {
            "command": command,
            "exit_code": completed.returncode,
            "timed_out": False,
        }

        output = (
            f"Exit code: {completed.returncode}\n"
            f"STDOUT:\n"
            f"{stdout or '(empty)'}\n"
            f"STDERR:\n"
            f"{stderr or '(empty)'}"
        )

        # IMPORTANT:
        # Non-zero exit code is a failed tool execution.
        # Never tell the agent that the command succeeded when it did not.
        if completed.returncode != 0:
            return ToolResult.fail(
                error_type="ShellCommandFailed",
                error=(f"Command exited with code {completed.returncode}."),
                metadata=metadata
                | {
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )

        return ToolResult.ok(
            output=output,
            metadata=metadata,
        )
