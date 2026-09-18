"""🩹 ApplyPatchTool — multi-hunk, multi-file, idempotency, guards.

Correctness note: hunks are REAL PatchHunk models (nested pydantic
models are not coerced from raw dicts by Args constructors)."""

from __future__ import annotations
from zipfile import Path

import pytest

from jimmy.tools.builtin.apply_patch import (
    ApplyPatchArgs,
    ApplyPatchTool,
    PatchHunk,
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write(workspace: Path, rel: str, content: str) -> None:
    p = workspace / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_apply_patch_multi_hunk_one_call(workspace: Path) -> None:
    _write(workspace, "app.py", "def a():\n    pass\n\n\ndef b():\n    pass\n")

    result = ApplyPatchTool().execute(
        ApplyPatchArgs(
            patches=[
                PatchHunk(
                    path="app.py",
                    search="def a():\n    pass",
                    replace='def a():\n    return "A"',
                ),
                PatchHunk(
                    path="app.py",
                    search="def b():\n    pass",
                    replace='def b():\n    return "B"',
                ),
            ]
        )
    )

    assert result.success
    text = (workspace / "app.py").read_text()
    assert 'return "A"' in text
    assert 'return "B"' in text
    assert "2 hunks" in result.output


def test_apply_patch_across_files(workspace: Path) -> None:
    _write(workspace, "a.py", "alpha\n")
    _write(workspace, "b.py", "beta\n")

    result = ApplyPatchTool().execute(
        ApplyPatchArgs(
            patches=[
                PatchHunk(path="a.py", search="alpha", replace="ALPHA"),
                PatchHunk(path="b.py", search="beta", replace="BETA"),
            ]
        )
    )

    assert result.success
    assert (workspace / "a.py").read_text() == "ALPHA\n"
    assert (workspace / "b.py").read_text() == "BETA\n"


def test_apply_patch_not_found_reports_and_keeps_file(workspace: Path) -> None:
    _write(workspace, "app.py", "real content\n")

    result = ApplyPatchTool().execute(
        ApplyPatchArgs(patches=[PatchHunk(path="app.py", search="nope", replace="x")])
    )

    assert not result.success
    assert "not found" in result.output
    assert (workspace / "app.py").read_text() == "real content\n"  # 未受影响


def test_apply_patch_ambiguous_requires_unique(workspace: Path) -> None:
    _write(workspace, "app.py", "pass\npass\n")

    result = ApplyPatchTool().execute(
        ApplyPatchArgs(patches=[PatchHunk(path="app.py", search="pass", replace="ok")])
    )

    assert not result.success
    assert "2 times" in result.output


def test_apply_patch_is_idempotent(workspace: Path) -> None:
    _write(workspace, "app.py", "OK\n")

    # search 已消失，replace 已存在 → 静默跳过，不报错
    result = ApplyPatchTool().execute(
        ApplyPatchArgs(patches=[PatchHunk(path="app.py", search="OLD", replace="OK")])
    )

    assert (workspace / "app.py").read_text() == "OK\n"


def test_apply_patch_empty_replace_deletes(workspace: Path) -> None:
    _write(workspace, "app.py", "keep\nDROP ME\nmore\n")

    result = ApplyPatchTool().execute(
        ApplyPatchArgs(patches=[PatchHunk(path="app.py", search="DROP ME\n", replace="")])
    )

    assert result.success
    assert "DROP ME" not in (workspace / "app.py").read_text()


def test_apply_patch_missing_file(workspace: Path) -> None:
    result = ApplyPatchTool().execute(
        ApplyPatchArgs(patches=[PatchHunk(path="ghost.py", search="a", replace="b")])
    )
    assert not result.success
    assert "does not exist" in result.output


def test_apply_patch_blocks_escape(workspace: Path) -> None:
    result = ApplyPatchTool().execute(
        ApplyPatchArgs(patches=[PatchHunk(path="../evil.py", search="a", replace="b")])
    )
    assert not result.success
    