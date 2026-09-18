"""🌿 GitTool — status/diff/add/commit/log on a real tmp repo."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from jimmy.tools.builtin.git_tool import GitArgs, GitTool

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "jimmy@test"], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Jimmy"], capture_output=True, check=True)
    return tmp_path


def _commit_all(repo: Path, message: str) -> None:
    (repo / "f.txt").write_text("one\n")
    GitTool().execute(GitArgs(action="add", paths=["f.txt"]))
    GitTool().execute(GitArgs(action="commit", message=message))


def test_git_status_runs(repo: Path) -> None:
    result = GitTool().execute(GitArgs(action="status"))
    assert result.success


def test_git_status_shows_dirty(repo: Path) -> None:
    (repo / "new.txt").write_text("x")
    result = GitTool().execute(GitArgs(action="status"))
    assert result.success
    assert "new.txt" in result.output


def test_git_add_requires_paths(repo: Path) -> None:
    result = GitTool().execute(GitArgs(action="add", paths=[]))
    assert not result.success
    assert result.error is not None
    assert "No paths" in result.error


def test_git_add_and_commit_and_log(repo: Path) -> None:
    (repo / "hello.txt").write_text("hi")

    add = GitTool().execute(GitArgs(action="add", paths=["hello.txt"]))
    assert add.success
    assert "Staged: hello.txt" in add.output

    commit = GitTool().execute(GitArgs(action="commit", message="✨ add hello"))
    assert commit.success

    log = GitTool().execute(GitArgs(action="log"))
    assert log.success
    assert "add hello" in log.output


def test_git_commit_requires_message(repo: Path) -> None:
    result = GitTool().execute(GitArgs(action="commit", message="   "))
    assert not result.success
    assert result.error is not None
    assert "message is required" in result.error


def test_git_diff_stat_and_full(repo: Path) -> None:
    _commit_all(repo, "init")
    (repo / "f.txt").write_text("one\ntwo\n")

    stat = GitTool().execute(GitArgs(action="diff"))
    assert stat.success

    full = GitTool().execute(GitArgs(action="diff", stat_only=False))
    assert full.success
    assert "two" in full.output


def test_git_diff_specific_path(repo: Path) -> None:
    _commit_all(repo, "init")

    # 🔑 git diff
    (repo / "other.txt").write_text("original\n")
    GitTool().execute(GitArgs(action="add", paths=["other.txt"]))
    GitTool().execute(GitArgs(action="commit", message="add other"))

    (repo / "other.txt").write_text("changed\n")

    result = GitTool().execute(GitArgs(action="diff", paths=["other.txt"]))
    assert result.success
    assert "other.txt" in result.output


def test_git_commit_empty_tree_fails_cleanly(repo: Path) -> None:
    # nothing staged → commit fails with a readable error, not a crash
    result = GitTool().execute(GitArgs(action="commit", message="✨ nothing"))
    assert not result.success
