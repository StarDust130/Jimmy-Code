from pathlib import Path

import pytest

from jimmy.tools.edit_file import (
    EditFileInput,
    EditFileTool,
)
from jimmy.tools.filesystem import Filesystem


def test_edit_file_replaces_exact_text(
    tmp_path: Path,
) -> None:
    file = tmp_path / "example.py"

    original = "def example():\n    return True\n"

    updated = "def example():\n    return False\n"

    file.write_text(
        original,
        encoding="utf-8",
    )

    tool = EditFileTool(
        Filesystem(tmp_path),
    )

    result = tool.execute(
        EditFileInput(
            path="example.py",
            old_text="    return True",
            new_text="    return False",
        )
    )

    assert result.success is True
    assert "Edited example.py successfully." in result.output

    assert (
        file.read_text(
            encoding="utf-8",
        )
        == updated
    )

    assert result.metadata["path"] == "example.py"
    assert result.metadata["characters_before"] == len(original)
    assert result.metadata["characters_after"] == len(updated)


def test_edit_file_fails_when_old_text_missing(
    tmp_path: Path,
) -> None:
    file = tmp_path / "example.py"

    file.write_text(
        "def example():\n    return True\n",
        encoding="utf-8",
    )

    tool = EditFileTool(
        Filesystem(tmp_path),
    )

    with pytest.raises(
        ValueError,
        match="not found",
    ):
        tool.execute(
            EditFileInput(
                path="example.py",
                old_text="does not exist",
                new_text="new code",
            )
        )


def test_edit_file_fails_when_old_text_is_ambiguous(
    tmp_path: Path,
) -> None:
    file = tmp_path / "example.py"

    file.write_text(
        "return True\nreturn True\n",
        encoding="utf-8",
    )

    tool = EditFileTool(
        Filesystem(tmp_path),
    )

    with pytest.raises(
        ValueError,
        match="matched 2 times",
    ):
        tool.execute(
            EditFileInput(
                path="example.py",
                old_text="return True",
                new_text="return False",
            )
        )


def test_edit_file_blocks_path_escape(
    tmp_path: Path,
) -> None:
    tool = EditFileTool(
        Filesystem(tmp_path),
    )

    with pytest.raises(
        ValueError,
        match="outside",
    ):
        tool.execute(
            EditFileInput(
                path="../secret.txt",
                old_text="secret",
                new_text="changed",
            )
        )
