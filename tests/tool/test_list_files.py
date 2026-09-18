"""🌳 ListFilesTool — tree listing, noise skipping, depth, guards."""

from __future__ import annotations

from zipfile import Path

import pytest

from jimmy.tools.builtin.list_files import ListFilesArgs, ListFilesTool


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_list_files_shows_tree(workspace: Path) -> None:
    (workspace / "src").mkdir()
    (workspace / "src" / "app.py").write_text("x = 1")
    (workspace / "README.md").write_text("hi")

    result = ListFilesTool().execute(ListFilesArgs())

    assert result.success

    assert "src/" in result.output
    assert "app.py" in result.output
    assert "README.md" in result.output


def test_list_files_skips_noise(workspace: Path) -> None:
    (workspace / "node_modules" / "pkg").mkdir(parents=True)
    (workspace / "node_modules" / "pkg" / "index.js").write_text("junk")
    (workspace / "app.py").write_text("x = 1")

    result = ListFilesTool().execute(ListFilesArgs())

    assert "node_modules" not in result.output
    assert "app.py" in result.output


def test_list_files_respects_depth(workspace: Path) -> None:
    deep = workspace / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "deep.py").write_text("x")

    shallow = ListFilesTool().execute(ListFilesArgs(max_depth=1))
    assert "deep.py" not in shallow.output

    deep_run = ListFilesTool().execute(ListFilesArgs(max_depth=4))
    assert "deep.py" in deep_run.output


def test_list_files_show_size(workspace: Path) -> None:
    (workspace / "sized.txt").write_text("12345")

    result = ListFilesTool().execute(ListFilesArgs(show_size=True))

    assert "sized.txt" in result.output
    assert "B)" in result.output


def test_list_files_blocks_escape(workspace: Path) -> None:
    result = ListFilesTool().execute(ListFilesArgs(path="../outside"))
    assert not result.success
    assert result.error is not None
    assert "outside workspace" in result.error


def test_list_files_missing_path(workspace: Path) -> None:
    result = ListFilesTool().execute(ListFilesArgs(path="nope"))
    assert not result.success


def test_list_files_caps_output(workspace: Path) -> None:
    for i in range(450):
        (workspace / f"f{i:03}.txt").write_text("x")

    result = ListFilesTool().execute(ListFilesArgs())
    assert "capped" in result.output
