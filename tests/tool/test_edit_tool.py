from pathlib import Path

from jimmy.tools.builtin.edit_files import (
    EditFilesArgs,
    EditFilesTool,
    FileEdit,
)


def test_single_edit(tmp_path: Path, monkeypatch) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a test file
    file = tmp_path / "README.md"
    file.write_text(
        "# Jimmy\n",
        encoding="utf-8",
    )

    # 3️⃣ Create the edit
    edit = FileEdit(
        path="README.md",
        search="# Jimmy",
        replace="# Jimmy Code",
    )

    # 4️⃣ Run the edit
    result = EditFilesTool().execute(EditFilesArgs(edits=[edit]))

    # 5️⃣ Check the result
    assert result.success is True
    assert file.read_text(encoding="utf-8") == "# Jimmy Code\n"


def test_multiple_file_edits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create test files
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"

    first.write_text("hello", encoding="utf-8")
    second.write_text("world", encoding="utf-8")

    # 3️⃣ Create multiple edits
    edits = [
        FileEdit(
            path="a.txt",
            search="hello",
            replace="hi",
        ),
        FileEdit(
            path="b.txt",
            search="world",
            replace="earth",
        ),
    ]

    # 4️⃣ Run all edits
    result = EditFilesTool().execute(EditFilesArgs(edits=edits))

    # 5️⃣ Check both files changed
    assert result.success is True
    assert first.read_text(encoding="utf-8") == "hi"
    assert second.read_text(encoding="utf-8") == "earth"


def test_old_text_new_text_compatibility(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a test file
    file = tmp_path / "README.md"
    file.write_text(
        "Hello Jimmy",
        encoding="utf-8",
    )

    # 3️⃣ Use the old field names
    edit = FileEdit(
        path="README.md",
        old_text="Hello Jimmy",
        new_text="Hello World",
    )

    # 4️⃣ Run the edit
    result = EditFilesTool().execute(EditFilesArgs(edits=[edit]))

    # 5️⃣ Check compatibility
    assert result.success is True
    assert file.read_text(encoding="utf-8") == "Hello World"


def test_missing_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Try to edit a missing file
    edit = FileEdit(
        path="missing.txt",
        search="hello",
        replace="hi",
    )

    # 3️⃣ Run the edit
    result = EditFilesTool().execute(EditFilesArgs(edits=[edit]))

    # 4️⃣ Check the error
    assert result.success is False
    assert "does not exist" in result.output


def test_search_text_not_found(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a test file
    file = tmp_path / "test.txt"
    file.write_text(
        "hello",
        encoding="utf-8",
    )

    # 3️⃣ Search for missing text
    edit = FileEdit(
        path="test.txt",
        search="missing",
        replace="hi",
    )

    # 4️⃣ Run the edit
    result = EditFilesTool().execute(EditFilesArgs(edits=[edit]))

    # 5️⃣ Check the error
    assert result.success is False
    assert "not found" in result.output


def test_duplicate_match_requires_replace_all(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create duplicate text
    file = tmp_path / "test.txt"
    file.write_text(
        "hello\nhello\n",
        encoding="utf-8",
    )

    # 3️⃣ Try replacing without replace_all
    edit = FileEdit(
        path="test.txt",
        search="hello",
        replace="hi",
    )

    # 4️⃣ Run the edit
    result = EditFilesTool().execute(EditFilesArgs(edits=[edit]))

    # 5️⃣ Check duplicate protection
    assert result.success is False
    assert "appears 2 times" in result.output

    # 6️⃣ Make sure nothing changed
    assert file.read_text(encoding="utf-8") == "hello\nhello\n"


def test_replace_all(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create duplicate text
    file = tmp_path / "test.txt"
    file.write_text(
        "hello\nhello\n",
        encoding="utf-8",
    )

    # 3️⃣ Replace every match
    edit = FileEdit(
        path="test.txt",
        search="hello",
        replace="hi",
        replace_all=True,
    )

    # 4️⃣ Run the edit
    result = EditFilesTool().execute(EditFilesArgs(edits=[edit]))

    # 5️⃣ Check every match changed
    assert result.success is True
    assert file.read_text(encoding="utf-8") == "hi\nhi\n"


def test_outside_workspace_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a file outside the workspace
    outside = tmp_path.parent / "outside.txt"
    outside.write_text(
        "secret",
        encoding="utf-8",
    )

    # 3️⃣ Try to edit outside the workspace
    edit = FileEdit(
        path="../outside.txt",
        search="secret",
        replace="changed",
    )

    # 4️⃣ Run the edit
    result = EditFilesTool().execute(EditFilesArgs(edits=[edit]))

    # 5️⃣ Check the security restriction
    assert result.success is False
    assert "outside workspace" in result.output

    # 6️⃣ Make sure the outside file was not changed
    assert outside.read_text(encoding="utf-8") == "secret"
