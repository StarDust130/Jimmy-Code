"""Boot, home screen, and the keyboard contract (ctrl+h/l/p, esc)."""

from __future__ import annotations

from conftest import leave_home, tui_test
from textual.widgets import Input

from tui.screens.home import HomeScreen
from tui.screens.palette import CommandPaletteScreen
from tui.widgets.chat_log import ChatLog
from tui.widgets.composer import Composer
from tui.widgets.messages import PairDivider, UserMessage
from tui.widgets.rows import TurnSummary
from tui.widgets.top_bar import TopBar


@tui_test
async def test_boots_with_home_on_top(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert len(app.screen_stack) == 2  # workspace + home
        assert app.sound.play_calls == 1  # startup jingle requested
        assert app.query_one(TopBar)
        assert app.query_one(ChatLog)
        assert app.query_one(Composer)


@tui_test
async def test_home_reveal_focuses_prompt(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        home = app.screen
        home._reveal_all()  # force the intro to finish
        await pilot.pause()
        assert home.query_one("#home-prompt", Input).has_focus


@tui_test
async def test_empty_submit_stays_on_home(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        home = app.screen
        home._reveal_all()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app._transcript == []


@tui_test
async def test_submit_from_home_enters_workspace(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        home = app.screen
        home._reveal_all()
        await pilot.pause()
        prompt = home.query_one("#home-prompt", Input)
        prompt.value = "hello jimmy"
        prompt.cursor_position = len(prompt.value)
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, HomeScreen)

        from conftest import settle

        await settle(app, pilot)

        assert app._transcript[0] == ("user", "hello jimmy")
        assert len(list(app.chat.query(UserMessage))) == 1
        assert len(list(app.chat.query(TurnSummary))) == 1
        assert len(list(app.chat.query(PairDivider))) == 1
        assert app.top_bar._hud_state == "done"
        assert app._busy is False


@tui_test
async def test_ctrl_n_from_chat_goes_home(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        app.composer.focus_input()
        await pilot.pause()

        await pilot.press("ctrl+n")  # chat → home (one-way)
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)


@tui_test
async def test_ctrl_n_without_input_focus_goes_home(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        app.set_focus(None)
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen)




@tui_test
async def test_ctrl_l_clears_input_not_chat(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        prompt = app.composer._prompt_input
        prompt.value = "draft text"
        await pilot.pause()

        await pilot.press("ctrl+l")
        await pilot.pause()
        assert prompt.value == ""
        assert app._transcript == []
        assert len(list(app.chat.query(UserMessage))) == 0


@tui_test
async def test_escape_on_workspace_is_a_safe_noop(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, CommandPaletteScreen)
        assert not app._busy


@tui_test
async def test_focus_watchdog_restores_composer(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        app.set_focus(None)
        await pilot.pause()
        app._heal_focus()  # what the 1s timer calls
        await pilot.pause()
        assert app.composer._prompt_input.has_focus
