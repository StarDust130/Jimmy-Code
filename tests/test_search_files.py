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
def test_search_files_can_be_scoped_to_a_project_folder(
    tmp_path: Path,
) -> None:
    target = tmp_path / "gitGraph"
    target.mkdir()
    (target / "app.js").write_text("const graph = true;\n")
    (tmp_path / "other.py").write_text("graph = False\n")

    result = SearchFilesTool(Filesystem(tmp_path)).execute(
        SearchFilesInput(query="graph", path="gitGraph")
    )

    assert result.success is True
    assert "gitGraph/app.js" in result.output
    assert "other.py" not in result.output
    assert result.metadata["path"] == "gitGraph"


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


@pytest.mark.skipif(
    which("rg") is None,
    reason="ripgrep is not installed",
)
def test_search_files_wildcard_lists_files_without_regex_error(
    tmp_path: Path,
) -> None:
    project = tmp_path / "gitGraph"
    project.mkdir()
    (project / "index.html").write_text("<main></main>\n")

    result = SearchFilesTool(Filesystem(tmp_path)).execute(
        SearchFilesInput(query="*", path="gitGraph")
    )

    assert result.success is True
    assert "gitGraph/index.html" in result.output
