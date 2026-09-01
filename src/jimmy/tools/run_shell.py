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

    background: bool = False


class RunShellTool(Tool):
    """
    Run a shell command inside the workspace.

    Normal commands run in the foreground and return their output.

    Long-running processes such as development servers should be
    started with background=true.
    """

    def __init__(
        self,
        filesystem: Filesystem,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        if timeout <= 0:
            raise ValueError(
                "timeout must be greater than zero.",
            )

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
            "Use this for tests, builds, linters, formatters, scripts, "
            "package commands, programs, and other commands that genuinely "
            "require a shell. "
            "\n\n"
            "For commands that are expected to finish, use background=false "
            "or omit background. "
            "For long-running processes such as development servers, use "
            "background=true so Jimmy does not wait for the process to exit. "
            "\n\n"
            "Do not use this for creating or editing files when a dedicated "
            "filesystem tool exists. "
            "For Git commits, use git_commit instead of git commit."
        )

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            read_only=False,
            destructive=True,
            requires_confirmation=True,
            timeout_seconds=float(
                self.timeout,
            ),
        )

    @property
    def input_model(self) -> type[BaseModel]:
        return RunShellInput

    def execute(
        self,
        arguments: BaseModel,
    ) -> ToolResult:
        args = RunShellInput.model_validate(
            arguments,
        )

        command = args.command.strip()

        if not command:
            raise ValueError(
                "'command' must be a non-empty string.",
            )

        check_shell_command(
            command,
        )

        # ======================================================
        # BACKGROUND PROCESS
        # ======================================================

        if args.background:
            try:
                process = subprocess.Popen(
                    command,
                    cwd=self.filesystem.root,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            except OSError as exc:
                raise RuntimeError(
                    f"Failed to start background command: {exc}",
                ) from exc

            return ToolResult.ok(
                output=(
                    "Started background process.\n"
                    f"PID: {process.pid}\n"
                    f"Command: {command}"
                ),
                metadata={
                    "command": command,
                    "background": True,
                    "pid": process.pid,
                    "started": True,
                },
            )

        # ======================================================
        # FOREGROUND PROCESS
        # ======================================================

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
            raise TimeoutError(
                f"Command timed out after "
                f"{self.timeout} seconds."
            ) from exc

        except OSError as exc:
            raise RuntimeError(
                f"Failed to start shell command: {exc}",
            ) from exc

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
            "background": False,
            "exit_code": result.returncode,
            "timed_out": False,
        }

        if result.returncode == 0:
            return ToolResult.ok(
                output=output,
                metadata=metadata,
            )

        return ToolResult(
            success=False,
            output=output,
            error_type="ShellCommandFailed",
            error=(
                f"Command exited with code "
                f"{result.returncode}."
            ),
            metadata=metadata,
        )