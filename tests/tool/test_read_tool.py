from pathlib import Path

from jimmy.tools.builtin.read_files import ReadFilesArgs, ReadFilesTool


def test_read_single_file(tmp_path: Path, monkeypatch) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a test file
    file = tmp_path / "hello.py"
    file.write_text("print('hello')", encoding="utf-8")

    # 3️⃣ Read the file
    result = ReadFilesTool().execute(ReadFilesArgs(paths=["hello.py"]))

    # 4️⃣ Check the result
    assert result.success is True
    assert "print('hello')" in result.output


def test_read_multiple_files(tmp_path: Path, monkeypatch) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create test files
    (tmp_path / "a.py").write_text("AAA", encoding="utf-8")
    (tmp_path / "b.py").write_text("BBB", encoding="utf-8")

    # 3️⃣ Read both files
    result = ReadFilesTool().execute(ReadFilesArgs(paths=["a.py", "b.py"]))

    # 4️⃣ Check both contents
    assert result.success is True
    assert "AAA" in result.output
    assert "BBB" in result.output


def test_missing_file(tmp_path: Path, monkeypatch) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Try to read a missing file
    result = ReadFilesTool().execute(ReadFilesArgs(paths=["missing.py"]))

    # 3️⃣ Check that it fails
    assert result.success is False
    assert "does not exist" in result.output


def test_directory_is_rejected(tmp_path: Path, monkeypatch) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a directory
    (tmp_path / "src").mkdir()

    # 3️⃣ Try to read the directory
    result = ReadFilesTool().execute(ReadFilesArgs(paths=["src"]))

    # 4️⃣ Check that it is rejected
    assert result.success is False
    assert "not a file" in result.output


def test_outside_workspace_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a file outside the workspace
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    # 3️⃣ Try to access it
    result = ReadFilesTool().execute(ReadFilesArgs(paths=["../outside.txt"]))

    # 4️⃣ Check the security restriction
    assert result.success is False
    assert "outside workspace" in result.output


def test_large_file_is_truncated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a large test file
    file = tmp_path / "large.txt"
    file.write_text("A" * 100, encoding="utf-8")

    # 3️⃣ Read with a small character limit
    result = ReadFilesTool().execute(
        ReadFilesArgs(
            paths=["large.txt"],
            max_chars_per_file=20,
        )
    )

    # 4️⃣ Check that output was truncated
    assert result.success is True
    assert "[truncated]" in result.output
    assert "A" * 21 not in result.output


def test_binary_file_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # 1️⃣ Use a temporary workspace
    monkeypatch.chdir(tmp_path)

    # 2️⃣ Create a binary file
    file = tmp_path / "image.bin"
    file.write_bytes(b"\xff\xfe\xfd\xfc")

    # 3️⃣ Try to read it as text
    result = ReadFilesTool().execute(ReadFilesArgs(paths=["image.bin"]))

    # 4️⃣ Check that binary content is rejected
    assert result.success is False
    assert "binary" in result.output.lower()
