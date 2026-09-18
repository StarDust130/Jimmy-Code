"""Live tool-row display for the dedicated tools — apply_patch ·
run_tests · git · list_files · write_file.  Pure mapping tests, no TUI
boot needed (tool_display is a pure function)."""

from __future__ import annotations

from tui.kit.helpers import tool_display

# ── apply_patch ─────────────────────────────────────────────────────────


def test_apply_patch_with_hunk_list() -> None:
    icon, action, detail = tool_display(
        "apply_patch", {"path": "src/app.py", "hunks": [{}, {}, {}]}
    )
    assert icon == "🩹"
    assert action == "Patching"
    assert detail == "src/app.py · 3 hunks"


def test_apply_patch_singular_hunk() -> None:
    _, _, detail = tool_display("apply_patch", {"path": "a.py", "hunks": [{}]})
    assert detail == "a.py · 1 hunk"


def test_apply_patch_counts_diff_markers() -> None:
    patch = "--- a\n+++ b\n@@ -1,2 +1,2 @@\n-x\n+y\n@@ -9 +9 @@\n-a\n+b\n"
    icon, _, detail = tool_display("apply_patch", {"patch": patch})
    assert icon == "🩹"
    assert detail == "2 hunks"


def test_apply_patch_path_only() -> None:
    _, action, detail = tool_display("apply_patch", {"path": "x.py"})
    assert action == "Patching"
    assert detail == "x.py"


def test_apply_patch_alias_name() -> None:
    icon, _, _ = tool_display("apply_patch_tool", {"path": "x.py"})
    assert icon == "🩹"


# ── run_tests ───────────────────────────────────────────────────────────


def test_run_tests_target_path() -> None:
    icon, action, detail = tool_display("run_tests", {"path": "tests/tool/"})
    assert icon == "🧪"
    assert action == "Testing"
    assert detail == "tests/tool/"


def test_run_tests_pattern() -> None:
    _, _, detail = tool_display("run_tests", {"pattern": "test_boot*"})
    assert detail == "test_boot*"


def test_run_tests_node_id() -> None:
    _, _, detail = tool_display("run_tests", {"node_id": "tests/tui/test_turn.py::test_submit"})
    assert detail == "tests/tui/test_turn.py::test_submit"


def test_run_tests_no_args() -> None:
    icon, action, detail = tool_display("run_tests", {})
    assert icon == "🧪"
    assert action == "Testing"
    assert detail == ""


# ── git tool ────────────────────────────────────────────────────────────


def test_git_commit_with_message() -> None:
    icon, action, detail = tool_display("git", {"command": "commit", "message": "fix tests"})
    assert icon == "📦"
    assert action == "Committing"
    assert detail == "git commit -m fix tests"


def test_git_status_via_args() -> None:
    icon, action, detail = tool_display("git", {"args": ["status"]})
    assert icon == "🌿"
    assert action == "Checking git"
    assert detail == "git status"


def test_git_push() -> None:
    icon, action, detail = tool_display("git", {"command": "push", "args": ["origin", "main"]})
    assert icon == "📡"
    assert action == "Syncing"
    assert detail == "git push origin main"


def test_git_add_paths() -> None:
    icon, action, detail = tool_display("git", {"command": "add", "paths": ["a.py", "b.py"]})
    assert icon == "🗃️"
    assert action == "Staging"
    assert detail == "git add a.py b.py"


def test_git_diff() -> None:
    icon, action, _ = tool_display("git", {"command": "diff"})
    assert icon == "🧾"
    assert action == "Checking diff"


def test_git_full_command_passthrough() -> None:
    icon, _, detail = tool_display("git", {"command": "git diff --stat"})
    assert icon == "🧾"
    assert detail == "git diff --stat"


def test_git_tool_alias() -> None:
    icon, _, _ = tool_display("git_tool", {"command": "status"})
    assert icon == "🌿"


def test_git_empty_args_falls_back() -> None:
    icon, action, detail = tool_display("git", {})
    assert icon == "🌿"
    assert action == "Git"
    assert detail == "git"


# ── existing dedicated tools still read well ────────────────────────────


def test_list_files_target() -> None:
    icon, action, detail = tool_display("list_files", {"path": "src/"})
    assert icon == "📂"
    assert action == "Listing"
    assert detail == "src/"


def test_write_file_target() -> None:
    icon, action, detail = tool_display("write_file", {"path": "new.py"})
    assert icon == "📝"
    assert action == "Writing"
    assert detail == "new.py"
