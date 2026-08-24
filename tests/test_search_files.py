from pathlib import Path
from shutil import which

import pytest

from jimmy.tools.filesystem import Filesystem
from jimmy.tools.search_files import (
    SearchFilesInput,
    SearchFilesTool,
)


@pytest.mark.skipif(
    which("rg") is None,
    reason="ripgrep is not installed",
)
def test_search_files(
    tmp_path: Path,
) -> None:
    file = tmp_path / "example.py"

    file.write_text(
        "def example():\n    pass\n",
        encoding="utf-8",
    )

    tool = SearchFilesTool(
        Filesystem(tmp_path),
    )

    result = tool.execute(
        SearchFilesInput(
            query="example",
        )
    )

    assert result.success is True
    assert "example.py" in result.output
    assert "example" in result.output
    assert result.metadata["query"] == "example"
    assert result.metadata["exit_code"] == 0


@pytest.mark.skipif(
    which("rg") is None,
    reason="ripgrep is not installed",
)
def test_search_files_no_match(
    tmp_path: Path,
) -> None:
    tool = SearchFilesTool(
        Filesystem(tmp_path),
    )

    result = tool.execute(
        SearchFilesInput(
            query="does_not_exist",
        )
    )

    assert result.success is True
    assert result.output == "No matches found."
    assert result.metadata["exit_code"] == 1


@pytest.mark.skipif(
    which("rg") is None,
    reason="ripgrep is not installed",
)
def test_search_files_empty_query(
    tmp_path: Path,
) -> None:
    tool = SearchFilesTool(
        Filesystem(tmp_path),
    )

    with pytest.raises(
        ValueError,
        match="non-empty",
    ):
        tool.execute(
            SearchFilesInput(
                query="",
            )
        )
