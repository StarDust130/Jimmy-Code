"""📚 Sessions TUI — list · resume · rename · delete · cleanup · restart."""

from __future__ import annotations

import asyncio
from typing import cast

from conftest import FakeProvider, settle, tui_test

from jimmy.llm.provider import LLMProvider
from jimmy.sessions import SessionStore
from tui.app import JimmyApp
from tui.screens.sessions import RenameScreen, SessionsScreen


def _app(tmp_path) -> tuple[JimmyApp, SessionStore]:
    store = SessionStore(tmp_path / "sessions.db")
    app = JimmyApp(provider=cast("LLMProvider", FakeProvider()), session_store=store)
    return app, store


@tui_test
async def test_sessions_screen_lists_newest_first(tmp_path) -> None:
    app, store = _app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        first = store.create_session(title="older work").id
        await asyncio.sleep(0.01)
        second = store.create_session(title="newer work").id

        app.action_sessions()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SessionsScreen)
        assert [s.id for s in screen._sessions] == [second, first]

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SessionsScreen)


@tui_test
async def test_resume_rebuilds_history_and_continues(tmp_path) -> None:
    app, store = _app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        sid = store.create_session(title="seed").id
        store.append_message(sid, "user", "hello there")
        store.append_message(sid, "assistant", "hi, ready")

        app.open_session(sid)
        await pilot.pause()
        await pilot.pause()

        assert app._session_id == sid
        assert [m.role for m in app.agent.history] == ["user", "assistant"]
        assert app.agent.history[0].content == "hello there"

        app.submit("one more")
        await settle(app, pilot)

        assert store.count_user_messages(sid) == 2
        contents = [m.content for m in store.get_messages(sid)]
        assert "one more" in contents


@tui_test
async def test_rename_flow(tmp_path) -> None:
    app, store = _app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        sid = store.create_session(title="old title").id
        app.action_sessions()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SessionsScreen)

        screen.action_session_rename()
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, RenameScreen)

        # ✂️ the old title arrives pre-selected → typing REPLACES it
        for ch in "better title":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        row = store.get_session(sid)
        assert row is not None  # 🧭 narrow Optional for Pylance
        assert row.title == "better title"
        assert row.title_source == "user"
        assert not isinstance(app.screen, RenameScreen)


@tui_test
async def test_delete_requires_double_press(tmp_path) -> None:
    app, store = _app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        old_id = store.create_session(title="old").id
        await asyncio.sleep(0.01)
        new_id = store.create_session(title="new").id

        app.action_sessions()
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SessionsScreen)
        assert screen._sessions[0].id == new_id  # newest first

        await pilot.press("d")  # arm confirmation
        await pilot.pause()
        assert store.get_session(new_id) is not None  # nothing deleted yet

        await pilot.press("d")  # confirm
        await pilot.pause()
        assert store.get_session(new_id) is None
        assert store.get_session(old_id) is not None

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SessionsScreen)


@tui_test
async def test_cleanup_cycles_policy(tmp_path) -> None:
    app, store = _app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        store.create_session(title="s")
        app.action_sessions()
        await pilot.pause()

        await pilot.press("c")  # 30 → 90
        await pilot.pause()
        assert store.get_setting("cleanup_days") == "90"

        await pilot.press("c")  # 90 → never
        await pilot.pause()
        assert store.get_setting("cleanup_days") == "never"

        await pilot.press("c")  # never → 15
        await pilot.pause()
        assert store.get_setting("cleanup_days") == "15"

        await pilot.press("c")  # 15 → 30
        await pilot.pause()
        assert store.get_setting("cleanup_days") == "30"


@tui_test
async def test_slash_and_ctrl_o_open_sessions(tmp_path) -> None:
    app, _store = _app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app._run_command("/sessions")
        await pilot.pause()
        assert isinstance(app.screen, SessionsScreen)
        await pilot.press("escape")
        await pilot.pause()

        await pilot.press("ctrl+o")
        await pilot.pause()
        assert isinstance(app.screen, SessionsScreen)


@tui_test
async def test_session_survives_restart(tmp_path) -> None:
    db = tmp_path / "sessions.db"
    store1 = SessionStore(db)
    sid = store1.create_session(title="crash test").id
    store1.append_message(sid, "user", "state before crash")
    store1.append_message(sid, "assistant", "saved")
    store1.close()

    app = JimmyApp(provider=cast("LLMProvider", FakeProvider()), session_store=SessionStore(db))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.open_session(sid)
        await pilot.pause()
        assert app.agent.history[0].content == "state before crash"
        assert app.agent.history[1].content == "saved"


@tui_test
async def test_auto_title_after_three_user_messages(tmp_path) -> None:
    app, store = _app(tmp_path)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        # 🗄️ drive the recorder directly — independent of the fake agent
        for text in ("first task", "second task", "third task"):
            app._record_user(text)
            await pilot.pause()
        # ⏳ let the autotitle worker finish
        for _ in range(20):
            rows = store.list_sessions()
            if rows and rows[0].title_source == "auto":
                break
            await pilot.pause()
        await asyncio.sleep(0.05)

        sessions = store.list_sessions()
        assert len(sessions) == 1
        row = sessions[0]
        assert row.title_source == "auto"
        assert row.title and row.title != "New session"
