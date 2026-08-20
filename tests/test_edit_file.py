from pathlib import Path

import pytest

from jimmy.tools.edit_file import EditFileTool
from jimmy.tools.filesystem import Filesystem


def test_edit_file_replaces_exact_text(tmp_path: Path) -> None:
    file = tmp_path / "auth.py"

    file.write_text(
        "def login():\n    return True\n",
        encoding="utf-8",
    )

    tool = EditFileTool(Filesystem(tmp_path))

    result = tool.execute(
        {
            "path": "auth.py",
            "old_text": "    return True",
            "new_text": "    return validate_user()",
        }
    )

    assert "Edited auth.py successfully." in result

    assert file.read_text(encoding="utf-8") == ("def login():\n    return validate_user()\n")


def test_edit_file_fails_when_old_text_missing(tmp_path: Path) -> None:
    file = tmp_path / "auth.py"
    file.write_text("def login():\n    return True\n", encoding="utf-8")

    tool = EditFileTool(Filesystem(tmp_path))

    with pytest.raises(ValueError, match="not found"):
        tool.execute(
            {
                "path": "auth.py",
                "old_text": "does not exist",
                "new_text": "new code",
            }
        )


def test_edit_file_fails_when_old_text_is_ambiguous(tmp_path: Path) -> None:
    file = tmp_path / "auth.py"

    file.write_text(
        "return True\nreturn True\n",
        encoding="utf-8",
    )

    tool = EditFileTool(Filesystem(tmp_path))

    with pytest.raises(ValueError, match="matched 2 times"):
        tool.execute(
            {
                "path": "auth.py",
                "old_text": "return True",
                "new_text": "return False",
            }
        )


def test_edit_file_blocks_path_escape(tmp_path: Path) -> None:
    tool = EditFileTool(Filesystem(tmp_path))

    with pytest.raises(ValueError, match="outside"):
        tool.execute(
            {
                "path": "../secret.txt",
                "old_text": "secret",
                "new_text": "changed",
            }
        )
