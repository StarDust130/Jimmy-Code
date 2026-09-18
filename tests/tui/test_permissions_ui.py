"""🛡️ Permission UI — picker + approval screens via the shared app fixture."""

from __future__ import annotations

import asyncio

from conftest import tui_test

from jimmy.permissions import Decision, PermissionMode, Risk
from tui.screens.permissions import ApprovalScreen, PermissionScreen


@tui_test
async def test_picker_sets_mode_and_closes(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.push_screen(PermissionScreen())
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, PermissionScreen)

        await pilot.press("3")  # 🔴 Full Access
        await pilot.pause()

        assert app.current_permission_mode() is PermissionMode.FULL
        assert not isinstance(app.screen, PermissionScreen)
        assert app.current_permission_label() == "🔴 Full Access"


@tui_test
async def test_slash_permissions_opens_picker(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app._run_command("/permissions")
        await pilot.pause()
        assert isinstance(app.screen, PermissionScreen)


@tui_test
async def test_permission_chip_exists_and_updates(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        chip = app.query_one("#chip-perm")  # rendered next to the model
        app.set_permission_mode(PermissionMode.ASK)
        await pilot.pause()
        assert app.current_permission_label() == "🟢 Ask"
        assert chip is not None


def _approval_request(app) -> dict:
    return app.agent.permissions.gate.new_request(
        tool_name="shell",
        arguments={"command": "git push origin main"},
        risk=Risk.DANGEROUS,
        summary="run shell command `git push origin main`",
    )


@tui_test
async def test_approval_allow_resolves_gate(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        gate = app.agent.permissions.gate
        request = _approval_request(app)

        waiter = asyncio.create_task(gate.wait(request["id"]))
        await asyncio.sleep(0)

        app.push_screen(ApprovalScreen(request))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ApprovalScreen)

        screen.action_allow()
        await pilot.pause()

        assert await asyncio.wait_for(waiter, timeout=2) is Decision.ALLOW
        assert not isinstance(app.screen, ApprovalScreen)


@tui_test
async def test_approval_deny_fails_closed(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        gate = app.agent.permissions.gate
        request = _approval_request(app)

        waiter = asyncio.create_task(gate.wait(request["id"]))
        await asyncio.sleep(0)

        app.push_screen(ApprovalScreen(request))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ApprovalScreen)

        screen.action_deny()  # esc path

        assert await asyncio.wait_for(waiter, timeout=2) is Decision.DENY


@tui_test
async def test_approval_session_grant(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        gate = app.agent.permissions.gate
        request = _approval_request(app)

        waiter = asyncio.create_task(gate.wait(request["id"]))
        await asyncio.sleep(0)

        app.push_screen(ApprovalScreen(request))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ApprovalScreen)

        screen.action_session()

        assert await asyncio.wait_for(waiter, timeout=2) is Decision.ALLOW
        assert "shell" in app.agent.permissions.session_grants


@tui_test
async def test_approval_full_access_upgrades_mode(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        gate = app.agent.permissions.gate
        request = _approval_request(app)

        waiter = asyncio.create_task(gate.wait(request["id"]))
        await asyncio.sleep(0)

        app.push_screen(ApprovalScreen(request))
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ApprovalScreen)

        screen.action_full_access()

        assert await asyncio.wait_for(waiter, timeout=2) is Decision.ALLOW
        assert app.current_permission_mode() is PermissionMode.FULL
