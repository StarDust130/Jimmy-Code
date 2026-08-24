import subprocess
from pathlib import Path

from jimmy.tools.filesystem import Filesystem
from jimmy.tools.git_commit import GitCommitTool


def init_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )

    subprocess.run(
        ["git", "config", "user.name", "Jimmy Test"],
        cwd=path,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "jimmy@example.com",
        ],
        cwd=path,
        check=True,
    )


def test_git_commit_each(tmp_path: Path) -> None:
    init_repo(tmp_path)

    file = tmp_path / "example.txt"
    file.write_text(
        "hello",
        encoding="utf-8",
    )

    tool = GitCommitTool(Filesystem(tmp_path))

    result = tool.execute(
        tool.input_model(
            mode="each",
        )
    )

    assert result.success is True
    assert len(result.metadata["commits"]) == 1

    log = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    assert "✨ add example" in log.stdout


def test_git_commit_single(
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)

    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"

    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")

    tool = GitCommitTool(Filesystem(tmp_path))

    result = tool.execute(
        tool.input_model(
            mode="single",
            message="✨ add files",
        )
    )

    assert result.success is True
    assert len(result.metadata["commits"]) == 1

    log = subprocess.run(
        ["git", "show", "--stat", "--oneline", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    assert "✨ add files" in log.stdout
    assert "first.txt" in log.stdout
    assert "second.txt" in log.stdout
