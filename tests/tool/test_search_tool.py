from pathlib import Path

from jimmy.tools.builtin.search_files import (
    SearchFilesArgs,
    SearchFilesTool,
)


def test_search_text_match(tmp_path: Path, monkeypatch) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a file with searchable text
    file = tmp_path / "auth.py"
    file.write_text(
        "def login():\n    return True\n",
        encoding="utf-8",
    )

    # 3️⃣ Search for the text
    result = SearchFilesTool().execute(SearchFilesArgs(query="login"))

    # 4️⃣ Check the match
    assert result.success is True
    assert "auth.py:1" in result.output


def test_search_filename_match(tmp_path: Path, monkeypatch) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a matching filename
    file = tmp_path / "authentication.py"
    file.write_text("x = 1", encoding="utf-8")

    # 3️⃣ Search by filename
    result = SearchFilesTool().execute(SearchFilesArgs(query="authentication"))

    # 4️⃣ Check the filename match
    assert result.success is True
    assert "authentication.py" in result.output
    assert "filename match" in result.output


def test_search_multiple_matches(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create multiple matching files
    (tmp_path / "a.py").write_text(
        "login()\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "login()\n",
        encoding="utf-8",
    )

    # 3️⃣ Search for the text
    result = SearchFilesTool().execute(SearchFilesArgs(query="login"))

    # 4️⃣ Check both files were found
    assert result.success is True
    assert "a.py" in result.output
    assert "b.py" in result.output


def test_search_no_match(tmp_path: Path, monkeypatch) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a file without the query
    (tmp_path / "hello.py").write_text(
        "print('hello')",
        encoding="utf-8",
    )

    # 3️⃣ Search for missing text
    result = SearchFilesTool().execute(SearchFilesArgs(query="authentication"))

    # 4️⃣ Check that nothing was found
    assert result.success is True
    assert "No matches found" in result.output


def test_search_respects_max_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create many matching files
    for index in range(10):
        (tmp_path / f"file_{index}.py").write_text(
            "login()\n",
            encoding="utf-8",
        )

    # 3️⃣ Limit the number of results
    result = SearchFilesTool().execute(
        SearchFilesArgs(
            query="login",
            max_results=3,
        )
    )

    # 4️⃣ Check that the limit was applied
    assert result.success is True
    assert "Showing first 3 results" in result.output


def test_search_ignores_common_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create an ignored directory
    ignored = tmp_path / "node_modules"
    ignored.mkdir()

    (ignored / "bad.js").write_text(
        "SECRET_LOGIN",
        encoding="utf-8",
    )

    # 3️⃣ Create a valid searchable file
    (tmp_path / "good.py").write_text(
        "login",
        encoding="utf-8",
    )

    # 4️⃣ Search the workspace
    result = SearchFilesTool().execute(SearchFilesArgs(query="login"))

    # 5️⃣ Check ignored folder is skipped
    assert result.success is True
    assert "good.py" in result.output
    assert "node_modules" not in result.output


def test_search_outside_workspace_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Try to search outside the workspace
    result = SearchFilesTool().execute(SearchFilesArgs(path="..", query="login"))

    # 3️⃣ Check the tool rejected it
    assert result.success is False

    # 4️⃣ Make sure an error exists
    assert result.error is not None

    # 5️⃣ Check the error message
    assert "outside workspace" in result.error
