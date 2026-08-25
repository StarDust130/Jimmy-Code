from pathlib import Path

from jimmy.permissions.manager import (
    PermissionAction,
    PermissionManager,
)
from jimmy.tools.edit_file import EditFileTool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.git_commit import GitCommitTool
from jimmy.tools.read_file import ReadFileTool
from jimmy.tools.run_shell import RunShellTool


def test_read_file_is_allowed(
    tmp_path: Path,
) -> None:
    manager = PermissionManager()

    tool = ReadFileTool(Filesystem(tmp_path))

    decision = manager.check(tool)

    assert decision.action == PermissionAction.ALLOW


def test_edit_file_is_allowed(
    tmp_path: Path,
) -> None:
    manager = PermissionManager()

    tool = EditFileTool(Filesystem(tmp_path))

    decision = manager.check(tool)

    assert decision.action == PermissionAction.ALLOW


def test_run_shell_requires_confirmation(
    tmp_path: Path,
) -> None:
    manager = PermissionManager()

    tool = RunShellTool(Filesystem(tmp_path))

    decision = manager.check(tool)

    assert decision.action == PermissionAction.ASK


def test_git_commit_requires_confirmation(
    tmp_path: Path,
) -> None:
    manager = PermissionManager()

    tool = GitCommitTool(
        filesystem=Filesystem(tmp_path),
        git_state=None,
    )

    decision = manager.check(tool)

    assert decision.action == PermissionAction.ASK


def test_full_access_allows_shell(
    tmp_path: Path,
) -> None:
    from jimmy.permissions.manager import PermissionMode

    manager = PermissionManager(
        mode=PermissionMode.FULL_ACCESS,
    )

    tool = RunShellTool(Filesystem(tmp_path))

    decision = manager.check(tool)

    assert decision.action == PermissionAction.ALLOW


def test_safe_only_blocks_shell(
    tmp_path: Path,
) -> None:
    from jimmy.permissions.manager import PermissionMode

    manager = PermissionManager(
        mode=PermissionMode.SAFE_ONLY,
    )

    tool = RunShellTool(Filesystem(tmp_path))

    decision = manager.check(tool)

    assert decision.action == PermissionAction.DENY
