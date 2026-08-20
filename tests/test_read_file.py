from pathlib import Path

import pytest

from jimmy.tools.filesystem import Filesystem
from jimmy.tools.read_file import ReadFileTool


def test_read_file(tmp_path: Path) -> None:
    file = tmp_path / "hello.txt"
    file.write_text("hello Jimmy", encoding="utf-8")

    tool = ReadFileTool(Filesystem(tmp_path))

    result = tool.execute({"path": "hello.txt"})

    assert result == "hello Jimmy"


def test_read_file_blocks_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    tool = ReadFileTool(Filesystem(tmp_path))

    with pytest.raises(ValueError, match="outside"):
        tool.execute({"path": "../secret.txt"})


def test_read_file_missing_file(tmp_path: Path) -> None:
    tool = ReadFileTool(Filesystem(tmp_path))

    with pytest.raises(FileNotFoundError):
        tool.execute({"path": "missing.txt"})
