import subprocess
from pathlib import Path

from jimmy.git.state import GitState


def init_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )


def test_baseline_tracks_preexisting_changes(
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)

    user_file = tmp_path / "user.txt"

    user_file.write_text(
        "user change",
        encoding="utf-8",
    )

    state = GitState(tmp_path)

    assert state.preexisting_files() == {
        "user.txt",
    }

    assert state.jimmy_files() == set()


def test_jimmy_files_are_new_session_changes(
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)

    user_file = tmp_path / "user.txt"

    user_file.write_text(
        "user change",
        encoding="utf-8",
    )

    state = GitState(tmp_path)

    jimmy_file = tmp_path / "jimmy.txt"

    jimmy_file.write_text(
        "Jimmy change",
        encoding="utf-8",
    )

    assert state.preexisting_files() == {
        "user.txt",
    }

    assert state.jimmy_files() == {
        "jimmy.txt",
    }
