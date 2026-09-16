"""Composer: paste sanitizing and ↑/↓ prompt history.

(Palette click tests live in test_palette.py — the earlier duplicate of
``test_palette_click_outside_card_closes`` here crashed collection
because ``pilot.click(Screen, ...)`` cannot query a screen.)
"""

from __future__ import annotations

from conftest import leave_home, settle, tui_test
from textual.widgets import Input

from tui.kit.helpers import MAX_PASTE_CHARS


@tui_test
async def test_multiline_paste_flattened(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        prompt = app.composer._prompt_input

        prompt.on_input_changed(Input.Changed(prompt, "line one\nline two\r\nline three"))
        assert prompt.value == "line one line two line three"


@tui_test
async def test_large_paste_is_kept_and_noticed(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        prompt = app.composer._prompt_input

        big = "x" * 500
        # Real paste path: assigning the value fires Input.Changed through
        # Textual's reactive system (same as a real paste); the handler
        # must keep it intact — under the cap, no newlines → untouched.
        prompt.value = big
        prompt.cursor_position = len(big)
        await pilot.pause()
        await pilot.pause()

        assert prompt.value == big
        assert len(prompt.value) == 500
        assert "\n" not in prompt.value


@tui_test
async def test_absurd_paste_is_capped(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        prompt = app.composer._prompt_input

        huge = "y" * (MAX_PASTE_CHARS + 10)
        prompt.on_input_changed(Input.Changed(prompt, huge))
        assert len(prompt.value) == MAX_PASTE_CHARS


@tui_test
async def test_prompt_history_up_down(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        app.submit("first prompt")
        await settle(app, pilot)
        app.submit("second prompt")
        await settle(app, pilot)
        assert app.composer._history == ["first prompt", "second prompt"]

        await pilot.press("up")
        assert app.composer._prompt_input.value == "second prompt"
        await pilot.press("up")
        assert app.composer._prompt_input.value == "first prompt"
        await pilot.press("down")
        assert app.composer._prompt_input.value == "second prompt"
        await pilot.press("down")
        assert app.composer._prompt_input.value == ""  # draft restored


@tui_test
async def test_history_dedupes_consecutive_duplicates(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        app.submit("a")
        await settle(app, pilot)
        app.submit("a")
        await settle(app, pilot)
        assert app.composer._history == ["a"]
