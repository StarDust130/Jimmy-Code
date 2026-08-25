from pathlib import Path

import pytest

from jimmy.tools.filesystem import Filesystem
from jimmy.tools.run_shell import (
    RunShellInput,
    RunShellTool,
)


def test_run_shell_success(
    tmp_path: Path,
) -> None:
    tool = RunShellTool(
        Filesystem(tmp_path),
    )

    result = tool.execute(
        RunShellInput(
            command="echo hello",
        )
    )

    assert result.success is True
    assert "Exit code: 0" in result.output
    assert "hello" in result.output
    assert result.metadata["exit_code"] == 0
    assert result.metadata["command"] == "echo hello"


def test_run_shell_failure(
    tmp_path: Path,
) -> None:
    tool = RunShellTool(
        Filesystem(tmp_path),
    )

    result = tool.execute(
        RunShellInput(
            command=('python -c "raise SystemExit(3)"'),
        )
    )

    assert result.success is True
    assert "Exit code: 3" in result.output
    assert result.metadata["exit_code"] == 3


def test_run_shell_timeout(
    tmp_path: Path,
) -> None:
    tool = RunShellTool(
        Filesystem(tmp_path),
        timeout=1,
    )

    with pytest.raises(
        TimeoutError,
        match="timed out",
    ):
        tool.execute(
            RunShellInput(
                command=('python -c "import time; time.sleep(5)"'),
            )
        )


def test_run_shell_empty_command(
    tmp_path: Path,
) -> None:
    tool = RunShellTool(
        Filesystem(tmp_path),
    )

    with pytest.raises(
        ValueError,
        match="non-empty",
    ):
        tool.execute(
            RunShellInput(
                command="",
            )
        )


def test_run_shell_returns_nonzero_exit_code(
    tmp_path: Path,
) -> None:
    tool = RunShellTool(
        Filesystem(tmp_path),
    )

    result = tool.execute(
        RunShellInput(
            command='python -c "raise SystemExit(2)"',
        )
    )

    assert result.success is True
    assert result.metadata["exit_code"] == 2
    assert "Exit code: 2" in result.output


def test_run_shell_returns_stdout_and_stderr(
    tmp_path: Path,
) -> None:
    tool = RunShellTool(
        Filesystem(tmp_path),
    )

    result = tool.execute(
        RunShellInput(
            command=("python -c \"print('stdout'); import sys; print('stderr', file=sys.stderr)\""),
        )
    )

    assert result.success is True
    assert "stdout" in result.output
    assert "stderr" in result.output