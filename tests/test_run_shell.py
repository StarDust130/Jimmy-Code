from pathlib import Path

import pytest

from jimmy.tools.filesystem import Filesystem
from jimmy.tools.run_shell import RunShellTool


def test_run_shell_success(tmp_path: Path) -> None:
    tool = RunShellTool(Filesystem(tmp_path))

    result = tool.execute({"command": "echo hello"})

    assert "Exit code: 0" in result
    assert "hello" in result


def test_run_shell_failure(tmp_path: Path) -> None:
    tool = RunShellTool(Filesystem(tmp_path))

    result = tool.execute({"command": 'python -c "raise SystemExit(3)"'})

    assert "Exit code: 3" in result


def test_run_shell_timeout(tmp_path: Path) -> None:
    tool = RunShellTool(Filesystem(tmp_path), timeout=1)

    with pytest.raises(TimeoutError, match="timed out"):
        tool.execute({"command": ('python -c "import time; time.sleep(5)"')})


def test_run_shell_empty_command(tmp_path: Path) -> None:
    tool = RunShellTool(Filesystem(tmp_path))

    with pytest.raises(ValueError, match="non-empty"):
        tool.execute({"command": ""})
