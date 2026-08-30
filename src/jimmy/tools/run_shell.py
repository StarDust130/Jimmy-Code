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
    """Run a shell command inside the current workspace."""

    def __init__(
        self,
        filesystem: Filesystem,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero.")

        self.filesystem = filesystem
        self.timeout = min(
            timeout,
            MAX_TIMEOUT,
        )

    @property
    def name(self) -> str:
        return "run_shell"

    @property
    def description(self) -> str:
        return (
            "Run a shell command inside the current workspace. "
            "Use this for tests, builds, linters, scripts, package "
            "commands, programs, and other commands that genuinely "
            "require a shell. "
            "Do not use this for creating or editing files when a "
            "dedicated filesystem tool exists. "
            "For Git commits, use git_commit instead of git commit."
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
            result = subprocess.run(
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

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        output = (
            f"Exit code: {result.returncode}\n"
            f"STDOUT:\n"
            f"{stdout or '(empty)'}\n"
            f"STDERR:\n"
            f"{stderr or '(empty)'}"
        )

        metadata = {
            "command": command,
            "exit_code": result.returncode,
            "timed_out": False,
        }

        # --------------------------------------------------
        # Successful command
        # --------------------------------------------------

        if result.returncode == 0:
            return ToolResult.ok(
                output=output,
                metadata=metadata,
            )

        # --------------------------------------------------
        # Failed command
        #
        # IMPORTANT:
        # Keep stdout/stderr/exit code in `output`.
        # The agent needs that information to understand
        # what went wrong and decide what to do next.
        # --------------------------------------------------

        return ToolResult(
            success=False,
            output=output,
            error_type="ShellCommandFailed",
            error=(f"Command exited with code {result.returncode}."),
            metadata=metadata,
        )
