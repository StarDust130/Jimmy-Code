import subprocess

from pydantic import BaseModel, ConfigDict

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult
from jimmy.utils.safety import check_shell_command


class RunShellInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str


class RunShellTool(Tool):
    """Run a shell command inside the workspace."""

    def __init__(
        self,
        filesystem: Filesystem,
        timeout: int = 120,
    ) -> None:
        self.filesystem = filesystem
        self.timeout = timeout

    @property
    def name(self) -> str:
        return "run_shell"

    @property
    def description(self) -> str:
        return (
            "Run a shell command inside the current workspace. "
            "Returns stdout, stderr, and the exit code."
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

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        return ToolResult.ok(
            output=(
                f"Exit code: {result.returncode}\n"
                f"STDOUT:\n"
                f"{stdout or '(empty)'}\n"
                f"STDERR:\n"
                f"{stderr or '(empty)'}"
            ),
            metadata={
                "command": command,
                "exit_code": result.returncode,
            },
        )
