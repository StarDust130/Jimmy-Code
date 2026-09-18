"""✍️ WriteFileTool — create, refuse-clobber, overwrite, guards."""

from __future__ import annotations

from zipfile import Path

import pytest

from jimmy.tools.builtin.write_file import WriteFileArgs, WriteFileTool


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_write_file_creates_new(workspace: Path) -> None:
    result = WriteFileTool().execute(WriteFileArgs(path="new/dir/tool.py", content="x = 1"))

    assert result.success
    assert (workspace / "new/dir/tool.py").read_text() == "x = 1"
    assert "Created" in result.output


def test_write_file_empty_content_ok(workspace: Path) -> None:
    result = WriteFileTool().execute(WriteFileArgs(path="empty.txt"))
    assert result.success
    assert (workspace / "empty.txt").read_text() == ""


def test_write_file_refuses_clobber(workspace: Path) -> None:
    (workspace / "existing.py").write_text("original")

    result = WriteFileTool().execute(WriteFileArgs(path="existing.py", content="clobbered"))

    assert not result.success
    assert result.error is not None
    assert "already exists" in result.error
    assert (workspace / "existing.py").read_text() == "original"  # 未受影响


def test_write_file_overwrite_when_allowed(workspace: Path) -> None:
    (workspace / "existing.py").write_text("original")

    result = WriteFileTool().execute(
        WriteFileArgs(path="existing.py", content="replaced", overwrite=True)
    )

    assert result.success
    assert "Rewrote" in result.output
    assert (workspace / "existing.py").read_text() == "replaced"


def test_write_file_refuses_directory(workspace: Path) -> None:
    (workspace / "adir").mkdir()

    result = WriteFileTool().execute(WriteFileArgs(path="adir", content="x"))

    assert not result.success
    assert "directory" in result.error


def test_write_file_blocks_escape(workspace: Path) -> None:
    result = WriteFileTool().execute(WriteFileArgs(path="../../etc/evil", content="x"))
    assert not result.success
