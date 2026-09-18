"""🛡️ Permission policy — risk classification + decisions in all modes."""

from __future__ import annotations

import asyncio

import pytest

from jimmy.permissions import (
    ApprovalGate,
    Decision,
    PermissionManager,
    PermissionMode,
    Risk,
    classify_risk,
    describe_action,
    mode_label,
)

ALL_MODES = list(PermissionMode)


# ── classification ──────────────────────────────────────────────────────


def test_safe_tools_classify_safe() -> None:
    for name in ("read_files", "search_files", "list_files"):
        assert classify_risk(name, {"path": "src/x.py"}) is Risk.SAFE


def test_write_tools_classify_write() -> None:
    for name in ("write_file", "edit_files", "apply_patch", "run_tests"):
        assert classify_risk(name, {"path": "src/x.py"}) is Risk.WRITE


def test_shell_is_dangerous() -> None:
    assert classify_risk("shell", {"command": "ls"}) is Risk.DANGEROUS


def test_git_readonly_subcommands_are_safe() -> None:
    for sub in ("status", "log", "diff", "branch"):
        assert classify_risk("git", {"command": sub}) is Risk.SAFE


def test_git_mutations_are_dangerous() -> None:
    for sub in ("commit", "reset", "push", "checkout", "clean"):
        assert classify_risk("git", {"command": sub}) is Risk.DANGEROUS


def test_git_unknown_subcommand_fails_closed() -> None:
    assert classify_risk("git", {"command": "become-robot-overlord"}) is Risk.DANGEROUS


def test_unknown_tool_fails_closed() -> None:
    assert classify_risk("definitely_not_a_tool", {}) is Risk.DANGEROUS


def test_absolute_path_escalates_read() -> None:
    assert classify_risk("read_files", {"paths": ["/etc/passwd"]}) is Risk.DANGEROUS


def test_parent_escape_escalates_write() -> None:
    assert classify_risk("write_file", {"path": "../../secrets.key"}) is Risk.DANGEROUS


def test_windows_absolute_path_escapes() -> None:
    assert classify_risk("read_files", {"path": "C:\\Windows\\system32"}) is Risk.DANGEROUS


def test_relative_paths_stay_safe() -> None:
    assert classify_risk("read_files", {"paths": ["src/app.py", "tests/x.py"]}) is Risk.SAFE


# ── decisions per mode ──────────────────────────────────────────────────


def test_safe_allowed_in_every_mode() -> None:
    for mode in ALL_MODES:
        assert PermissionManager(mode).check("read_files", {"path": "a.py"}) is Decision.ALLOW


def test_write_asks_in_ask_mode() -> None:
    assert (
        PermissionManager(PermissionMode.ASK).check("write_file", {"path": "a.py"}) is Decision.ASK
    )


def test_write_allowed_in_auto_and_full() -> None:
    assert (
        PermissionManager(PermissionMode.AUTO).check("edit_files", {"path": "a.py"})
        is Decision.ALLOW
    )
    assert (
        PermissionManager(PermissionMode.FULL).check("edit_files", {"path": "a.py"})
        is Decision.ALLOW
    )


def test_shell_asks_in_ask_and_auto() -> None:
    assert PermissionManager(PermissionMode.ASK).check("shell", {"command": "ls"}) is Decision.ASK
    assert PermissionManager(PermissionMode.AUTO).check("shell", {"command": "ls"}) is Decision.ASK


def test_shell_allowed_in_full() -> None:
    assert (
        PermissionManager(PermissionMode.FULL).check("shell", {"command": "ls"}) is Decision.ALLOW
    )


def test_run_tests_auto_allowed() -> None:
    assert (
        PermissionManager(PermissionMode.AUTO).check("run_tests", {"path": "tests/"})
        is Decision.ALLOW
    )


def test_git_status_auto_allowed_commit_asks() -> None:
    m = PermissionManager(PermissionMode.AUTO)
    assert m.check("git", {"command": "status"}) is Decision.ALLOW
    assert m.check("git", {"command": "commit", "message": "x"}) is Decision.ASK
    assert m.check("git", {"command": "reset", "args": ["--hard"]}) is Decision.ASK


def test_outside_workspace_read_asks_in_auto() -> None:
    assert (
        PermissionManager(PermissionMode.AUTO).check("read_files", {"path": "/etc/passwd"})
        is Decision.ASK
    )


def test_session_grant_allows_dangerous_tool() -> None:
    m = PermissionManager(PermissionMode.AUTO)
    assert m.check("shell", {"command": "ls"}) is Decision.ASK
    m.grant_for_session("shell")
    assert m.check("shell", {"command": "anything"}) is Decision.ALLOW
    # grant is name-specific
    assert m.check("git", {"command": "push"}) is Decision.ASK


def test_set_mode_applies_immediately() -> None:
    m = PermissionManager(PermissionMode.AUTO)
    assert m.check("shell", {"command": "ls"}) is Decision.ASK
    m.set_mode(PermissionMode.FULL)
    assert m.check("shell", {"command": "ls"}) is Decision.ALLOW
    m.set_mode(PermissionMode.ASK)
    assert m.check("write_file", {"path": "a.py"}) is Decision.ASK


def test_mode_labels() -> None:
    assert mode_label(PermissionMode.ASK) == "🟢 Ask"
    assert mode_label(PermissionMode.AUTO) == "🟡 Auto"
    assert mode_label(PermissionMode.FULL) == "🔴 Full Access"


def test_describe_actions() -> None:
    assert "git commit" in describe_action("git", {"command": "commit", "message": "x"})
    assert "shell command" in describe_action("shell", {"command": "rm -rf build/"})
    assert "write file" in describe_action("write_file", {"path": "src/a.py"})
    assert "patch" in describe_action("apply_patch", {"path": "src/a.py"})
    assert "tests" in describe_action("run_tests", {"path": "tests/tool/"})


# ── approval gate (async) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_resolve_roundtrip() -> None:
    gate = ApprovalGate()
    req = gate.new_request(
        tool_name="shell",
        arguments={"command": "ls"},
        risk=Risk.DANGEROUS,
        summary="run shell command `ls`",
    )
    assert req["reason"]

    async def answer() -> Decision:
        return await gate.wait(req["id"])

    task = asyncio.create_task(answer())
    await asyncio.sleep(0)
    # resolve BEFORE wait registers → must still win (pre-registered future)
    assert gate.resolve(req["id"], Decision.ALLOW) is True
    assert await asyncio.wait_for(task, 2) is Decision.ALLOW
    assert gate.pending() == ()


@pytest.mark.asyncio
async def test_gate_cancel_all_fails_closed() -> None:
    gate = ApprovalGate()
    req = gate.new_request(tool_name="shell", arguments={}, risk=Risk.DANGEROUS, summary="s")

    async def answer() -> Decision:
        return await gate.wait(req["id"])

    task = asyncio.create_task(answer())
    await asyncio.sleep(0)
    gate.cancel_all()
    assert await asyncio.wait_for(task, 2) is Decision.DENY
