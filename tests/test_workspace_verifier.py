from __future__ import annotations

from pathlib import Path

from jimmy.agent.main_loop.workspace_verifier import (
    WorkspaceVerifier,
)


def test_edit_file_detects_real_change(
    tmp_path: Path,
) -> None:
    file = tmp_path / "main.py"

    file.write_text(
        "hello\n",
        encoding="utf-8",
    )

    verifier = WorkspaceVerifier(
        tmp_path,
    )

    before = verifier.capture(
        tool_name="edit_file",
        arguments={
            "path": "main.py",
        },
    )

    file.write_text(
        "hello Jimmy\n",
        encoding="utf-8",
    )

    result = verifier.verify(
        tool_name="edit_file",
        arguments={
            "path": "main.py",
        },
        before=before,
    )

    assert result.verified is True
    assert result.changed is True
    assert result.paths == ("main.py",)


def test_edit_file_detects_no_change(
    tmp_path: Path,
) -> None:
    file = tmp_path / "main.py"

    file.write_text(
        "hello\n",
        encoding="utf-8",
    )

    verifier = WorkspaceVerifier(
        tmp_path,
    )

    before = verifier.capture(
        tool_name="edit_file",
        arguments={
            "path": "main.py",
        },
    )

    # Nothing changed.
    result = verifier.verify(
        tool_name="edit_file",
        arguments={
            "path": "main.py",
        },
        before=before,
    )

    assert result.verified is False
    assert result.changed is False
    assert "content did not change" in result.reason


def test_edit_file_detects_missing_file(
    tmp_path: Path,
) -> None:
    file = tmp_path / "main.py"

    file.write_text(
        "hello\n",
        encoding="utf-8",
    )

    verifier = WorkspaceVerifier(
        tmp_path,
    )

    before = verifier.capture(
        tool_name="edit_file",
        arguments={
            "path": "main.py",
        },
    )

    file.unlink()

    result = verifier.verify(
        tool_name="edit_file",
        arguments={
            "path": "main.py",
        },
        before=before,
    )

    assert result.verified is False
    assert "does not exist" in result.reason


def test_create_file_is_verified(
    tmp_path: Path,
) -> None:
    verifier = WorkspaceVerifier(
        tmp_path,
    )

    arguments = {
        "files": [
            {
                "path": "hello.txt",
                "content": "hello Jimmy",
            }
        ]
    }

    before = verifier.capture(
        tool_name="create_files",
        arguments=arguments,
    )

    (tmp_path / "hello.txt").write_text(
        "hello Jimmy",
        encoding="utf-8",
    )

    result = verifier.verify(
        tool_name="create_files",
        arguments=arguments,
        before=before,
    )

    assert result.verified is True
    assert result.changed is True
    assert result.paths == ("hello.txt",)


def test_create_file_detects_missing_creation(
    tmp_path: Path,
) -> None:
    verifier = WorkspaceVerifier(
        tmp_path,
    )

    arguments = {
        "files": [
            {
                "path": "hello.txt",
                "content": "hello Jimmy",
            }
        ]
    }

    before = verifier.capture(
        tool_name="create_files",
        arguments=arguments,
    )

    result = verifier.verify(
        tool_name="create_files",
        arguments=arguments,
        before=before,
    )

    assert result.verified is False
    assert "was not created" in result.reason


def test_path_cannot_escape_workspace(
    tmp_path: Path,
) -> None:
    verifier = WorkspaceVerifier(
        tmp_path,
    )

    try:
        verifier.capture(
            tool_name="edit_file",
            arguments={
                "path": "../outside.txt",
            },
        )
    except ValueError as exc:
        assert "escapes workspace" in str(exc)
    else:
        raise AssertionError(
            "Expected workspace escape to be rejected."
        )