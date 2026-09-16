"""Agent event stream → timeline rendering, errors, retry, copy."""

from __future__ import annotations

import asyncio

from conftest import FakeEvent, leave_home, settle, tui_test, usage

from tui.widgets.messages import AssistantMessage, ErrorCard, PairDivider, SystemNote, UserMessage
from tui.widgets.rows import LiveToolStatus, ThinkingRow, TurnSummary


@tui_test
async def test_turn_renders_text_summary_and_divider(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        def make_stream(text: str):
            async def _stream(t: str):
                yield FakeEvent("llm_start", model="m1", step=1)
                yield FakeEvent("text", text="Hello ")
                yield FakeEvent("text", text="world")
                yield FakeEvent("llm_done", latency=0.5, usage=usage(100, 10))

            return _stream

        app.agent.stream_impl = make_stream("hi")
        app.submit("hi")
        await settle(app, pilot)

        assert app._transcript == [("user", "hi"), ("assistant", "Hello world")]
        assert app._total_in == 100
        assert app._total_out == 10
        assert app._turn_steps == 1
        assert len(list(app.chat.query(UserMessage))) == 1
        assert len(list(app.chat.query(AssistantMessage))) == 1
        assert len(list(app.chat.query(TurnSummary))) == 1
        assert len(list(app.chat.query(PairDivider))) == 1
        assert len(list(app.chat.query(ThinkingRow))) == 0  # dismissed
        assert app.top_bar._hud_state == "done"
        assert app._busy is False


@tui_test
async def test_turn_with_tools_and_rounds(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        def make_stream(text: str):
            async def _stream(t: str):
                yield FakeEvent("llm_start", model="m", step=1)
                yield FakeEvent(
                    "tool_start", id="t1", name="read_file", arguments={"path": "README.md"}
                )
                yield FakeEvent("tool_done", id="t1", latency=0.084)
                yield FakeEvent("llm_start", model="m", step=2)
                yield FakeEvent("text", text="done")
                yield FakeEvent("llm_done", latency=0.2, usage=usage(50, 5))

            return _stream

        app.agent.stream_impl = make_stream("do it")
        app.submit("do it")
        await settle(app, pilot)

        assert app._turn_tools == 1
        assert app._turn_steps == 2
        assert app._total_in == 50
        assert app._transcript[-1] == ("assistant", "done")

        rows = list(app.chat.query(LiveToolStatus))
        assert len(rows) == 1
        assert rows[0].action == "Reading"
        assert rows[0].detail == "README.md"
        assert rows[0]._anim_timer is None  # finished → anim stopped

        assert len(list(app.chat.query(ThinkingRow))) == 0
        assert app.top_bar._activity is None
        assert len(list(app.chat.query(TurnSummary))) == 1


@tui_test
async def test_tool_failure_marks_row_failed(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        def make_stream(text: str):
            async def _stream(t: str):
                yield FakeEvent("tool_start", id="t1", name="edit_file", arguments={"path": "x.ts"})
                yield FakeEvent("tool_error", id="t1", error=RuntimeError("validation error"))

            return _stream

        app.agent.stream_impl = make_stream("edit")
        app.submit("edit")
        await settle(app, pilot)

        rows = list(app.chat.query(LiveToolStatus))
        assert len(rows) == 1
        assert rows[0].action == "Editing"
        assert rows[0].detail == "x.ts"
        assert rows[0]._anim_timer is None
        assert app.top_bar._hud_state == "done"  # turn still completes


@tui_test
async def test_turn_error_shows_card_and_retry(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        def make_stream(text: str):
            async def _stream(t: str):
                yield FakeEvent("llm_start", model="m", step=1)
                raise RuntimeError("HTTP 503 Service Unavailable")

            return _stream

        app.agent.stream_impl = make_stream("boom")
        app.submit("boom")
        await settle(app, pilot)

        assert app.top_bar._hud_state == "error"
        assert len(list(app.chat.query(ErrorCard))) == 1
        assert app._transcript == [("user", "boom")]

        assert app.action_retry_last() is True
        await settle(app, pilot)
        # failed user line was popped before resubmitting → no duplicate
        assert app._transcript == [("user", "boom")]
        assert len(list(app.chat.query(ErrorCard))) == 2


@tui_test
async def test_retry_refuses_while_busy(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        app._busy = True
        assert app.action_retry_last() is False
        app._busy = False


@tui_test
async def test_escape_interrupts_running_turn(app) -> None:
    release = asyncio.Event()
    started = asyncio.Event()

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        def make_stream(text: str):
            async def _stream(t: str):
                started.set()
                yield FakeEvent("llm_start", model="m", step=1)
                await release.wait()  # block until cancelled
                yield FakeEvent("text", text="late")
                yield FakeEvent("llm_done", latency=0.1, usage=usage())

            return _stream

        app.agent.stream_impl = make_stream("long")
        app.submit("long task")

        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        await pilot.pause()
        assert app._busy is True

        await pilot.press("escape")
        for _ in range(100):
            if not app._busy:
                break
            await asyncio.sleep(0.01)
            await pilot.pause()

        assert app._busy is False
        assert app.top_bar._hud_state == "interrupted"
        assert len(list(app.chat.query(SystemNote))) >= 1
        assert app._transcript == [("user", "long task")]  # no assistant
        release.set()


@tui_test
async def test_copy_helpers_use_transcript_only(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        def make_stream(text: str):
            async def _stream(t: str):
                yield FakeEvent("text", text="Hello world")
                yield FakeEvent("llm_done", latency=0.1, usage=usage(10, 2))

            return _stream

        app.agent.stream_impl = make_stream("hi")
        app.submit("hi")
        await settle(app, pilot)

        last = app._exchange_text("last")
        assert last == [("user", "hi"), ("assistant", "Hello world")]
        assert app._exchange_text("all") == last

        # ctrl+c must not raise even if the clipboard backend fails
        await pilot.press("ctrl+c")
        await pilot.pause()


@tui_test
async def test_selection_release_copies_text(app, monkeypatch) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        captured: list[str] = []
        monkeypatch.setattr(app, "copy_to_clipboard", lambda text: captured.append(text))
        monkeypatch.setattr(
            "tui.widgets.chat_log.ChatLog.selected_text",
            property(lambda self: "  selected words  "),
            raising=False,
        )

        app.chat._maybe_copy_selection()
        assert captured == ["selected words"]

        # whitespace-only selection is ignored
        monkeypatch.setattr(
            "tui.widgets.chat_log.ChatLog.selected_text",
            property(lambda self: "   "),
            raising=False,
        )
        app.chat._maybe_copy_selection()
        assert captured == ["selected words"]
