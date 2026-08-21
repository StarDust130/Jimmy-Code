from pathlib import Path

import pytest

from jimmy.tools.filesystem import Filesystem
from jimmy.tools.run_shell import RunShellTool
from jimmy.utils.limits import truncate_output
from jimmy.utils.safety import check_shell_command


def test_truncate_output() -> None:
    result = truncate_output("a" * 100, limit=20)

    assert len(result) > 20
    assert "[Output truncated:" in result


def test_short_output_is_unchanged() -> None:
    result = truncate_output("hello", limit=20)

    assert result == "hello"


def test_blocks_rm_rf_root() -> None:
    with pytest.raises(PermissionError):
        check_shell_command("rm -rf /")


def test_blocks_windows_delete() -> None:
    with pytest.raises(PermissionError):
        check_shell_command("del /s /q C:\\")


def test_safe_command_is_allowed() -> None:
    check_shell_command("pytest")


def test_run_shell_blocks_dangerous_command(tmp_path: Path) -> None:
    tool = RunShellTool(Filesystem(tmp_path))

    with pytest.raises(PermissionError):
        tool.execute({"command": "rm -rf /"})
