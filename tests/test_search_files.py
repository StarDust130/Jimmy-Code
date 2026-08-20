from pathlib import Path
from shutil import which

import pytest

from jimmy.tools.filesystem import Filesystem
from jimmy.tools.search_files import SearchFilesTool


@pytest.mark.skipif(which("rg") is None, reason="ripgrep is not installed")
def test_search_files(tmp_path: Path) -> None:
    file = tmp_path / "auth.py"
    file.write_text(
        "def authenticate():\n    pass\n",
        encoding="utf-8",
    )

    tool = SearchFilesTool(Filesystem(tmp_path))

    result = tool.execute({"query": "authenticate"})

    assert "auth.py" in result
    assert "authenticate" in result


@pytest.mark.skipif(which("rg") is None, reason="ripgrep is not installed")
def test_search_files_no_match(tmp_path: Path) -> None:
    tool = SearchFilesTool(Filesystem(tmp_path))

    result = tool.execute({"query": "does_not_exist"})

    assert result == "No matches found."
