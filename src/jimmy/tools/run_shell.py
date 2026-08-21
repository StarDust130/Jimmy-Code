import subprocess
from typing import Any

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.utils.safety import check_shell_command


class RunShellTool(Tool):
    """Run a shell command inside the working directory."""

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
            "Run a shell command inside the working directory. "
            "Returns stdout, stderr, and exit code."
        )

    def execute(self, arguments: dict[str, Any]) -> str:
        command = arguments.get("command")

        if not isinstance(command, str) or not command.strip():
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
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"Command timed out after {self.timeout} seconds.") from exc

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        return (
            f"Exit code: {result.returncode}\n"
            f"STDOUT:\n{stdout or '(empty)'}\n"
            f"STDERR:\n{stderr or '(empty)'}"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to run inside the working directory.",
                }
            },
            "required": ["command"],
            "additionalProperties": False,
        }
