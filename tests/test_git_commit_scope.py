from __future__ import annotations

import subprocess
from pathlib import Path

from jimmy.git.state import GitState
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.git_commit import (
    GitCommitInput,
    GitCommitTool,
)


def run_git(
    root: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0, (
        f"Git command failed: git {' '.join(args)}\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )

    return result


def test_commit_only_selected_file(
    tmp_path: Path,
) -> None:
    # ---------------------------------------------------------
    # Create repository
    # ---------------------------------------------------------

    run_git(
        tmp_path,
        "init",
    )

    run_git(
        tmp_path,
        "config",
        "user.name",
        "Test",
    )

    run_git(
        tmp_path,
        "config",
        "user.email",
        "test@example.com",
    )

    # ---------------------------------------------------------
    # Create baseline files
    # ---------------------------------------------------------

    a = tmp_path / "a.py"
    b = tmp_path / "b.py"

    a.write_text(
        "a = 1\n",
        encoding="utf-8",
    )

    b.write_text(
        "b = 1\n",
        encoding="utf-8",
    )

    run_git(
        tmp_path,
        "add",
        ".",
    )

    run_git(
        tmp_path,
        "commit",
        "-m",
        "baseline",
    )

    # ---------------------------------------------------------
    # Create two independent changes
    # ---------------------------------------------------------

    a.write_text(
        "a = 2\n",
        encoding="utf-8",
    )

    b.write_text(
        "b = 2\n",
        encoding="utf-8",
    )

    # ---------------------------------------------------------
    # Create tool
    # ---------------------------------------------------------

    git_state = GitState(
        tmp_path,
    )

    tool = GitCommitTool(
        filesystem=Filesystem(
            tmp_path,
        ),
        git_state=git_state,
    )

    # ---------------------------------------------------------
    # Commit ONLY a.py
    # ---------------------------------------------------------

    result = tool.execute(
        GitCommitInput(
            paths=["a.py"],
            mode="single",
        ),
    )

    assert result.success is True

    # ---------------------------------------------------------
    # Verify the latest commit
    # ---------------------------------------------------------

    latest_commit = run_git(
        tmp_path,
        "show",
        "--format=",
        "--name-only",
        "HEAD",
    )

    committed_files = {line.strip() for line in latest_commit.stdout.splitlines() if line.strip()}

    assert "a.py" in committed_files
    assert "b.py" not in committed_files

    # ---------------------------------------------------------
    # Verify the committed content
    # ---------------------------------------------------------

    committed_a = run_git(
        tmp_path,
        "show",
        "HEAD:a.py",
    )

    assert committed_a.stdout == "a = 2\n"

    # ---------------------------------------------------------
    # Verify b.py is STILL uncommitted
    # ---------------------------------------------------------

    status = run_git(
        tmp_path,
        "status",
        "--short",
        "--",
        "b.py",
    )

    assert status.stdout.strip() != ""

    # ---------------------------------------------------------
    # Verify a.py is clean
    # ---------------------------------------------------------

    status = run_git(
        tmp_path,
        "status",
        "--short",
        "--",
        "a.py",
    )

    assert status.stdout.strip() == ""
