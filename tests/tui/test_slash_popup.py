"""Slash-command autocomplete: open/filter/Tab/Enter/Esc, in BOTH the
workspace composer and the home hero."""

from __future__ import annotations

import pytest
from conftest import leave_home, settle, tui_test

from tui.kit.theme import THEME
from tui.screens.home import HomeScreen
from tui.screens.models import ModelScreen
from tui.widgets.composer import Composer


@tui_test
async def test_popup_opens_on_slash_with_all_commands(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        slash = app.composer._slash
        assert slash is not None
        assert not slash.is_open

        await pilot.press("/")
        await pilot.pause()

        assert slash.is_open
        assert len(slash._items) == len(Composer.COMMANDS)


@tui_test
async def test_popup_filters_by_prefix(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        for char in "/mo":
            await pilot.press(char)
        await pilot.pause()

        assert app.composer._slash._items == ["/model"]


@tui_test
async def test_tab_completes_highlighted_command(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        for char in "/mo":
            await pilot.press(char)
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()

        assert app.composer._prompt_input.value == "/model"
        assert app.composer._slash.is_open  # stays open → Enter runs it


@tui_test
async def test_enter_runs_highlighted_command_from_prefix(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        for char in "/cl":  # unique prefix of /clear
            await pilot.press(char)
        await pilot.pause()

        app.chat.append = lambda *a, **k: None  # silence UI noise
        await pilot.press("enter")
        await pilot.pause()

        assert app.composer._prompt_input.value == ""  # cleared, not "/cl"
        assert not app.composer._slash.is_open


@tui_test
async def test_enter_with_model_prefix_opens_model_screen(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        for char in "/mo":
            await pilot.press(char)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, ModelScreen)


@tui_test
async def test_esc_dismisses_popup_and_keeps_text(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        await pilot.press("/")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert not app.composer._slash.is_open
        assert app.composer._prompt_input.value == "/"
        assert not isinstance(app.screen, ModelScreen)


@tui_test
async def test_up_down_history_when_popup_closed(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        app.submit("alpha")
        await settle(app, pilot)

        await pilot.press("up")
        await pilot.pause()
        assert app.composer._prompt_input.value == "alpha"


@tui_test
async def test_popup_also_works_on_home(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        home = app.screen
        assert isinstance(home, HomeScreen)
        home._reveal_all()
        await pilot.pause()

        slash = home._slash
        assert slash is not None

        for char in "/the":  # unique prefix of /theme
            await pilot.press(char)
        await pilot.pause()

        assert slash.is_open
        assert slash._items == ["/theme"]

        await pilot.press("enter")  # runs /theme from HOME
        await pilot.pause()
        await pilot.pause()

        assert THEME["name"] == "ember"
        assert isinstance(app.screen, HomeScreen)  # stayed on home


@pytest.mark.parametrize(
    ("needle", "haystack", "matched"),
    [
        ("glmflash", "groq/glm-4.6-flash", True),  # spaces stripped
        ("gpt4o", "openai/gpt-4o", True),
        ("csonnet", "anthropic/claude-sonnet-4-5", True),
        ("xyzzy", "openai/gpt-4o", False),
    ],
)
def test_fuzzy_score(needle: str, haystack: str, matched: bool) -> None:
    from tui.screens.models import _fuzzy_score

    score = _fuzzy_score(needle, haystack)
    assert (score > 0) is matched


def test_fuzzy_substring_beats_subsequence() -> None:
    from tui.screens.models import _fuzzy_score

    exact = _fuzzy_score("gpt-4o", "openai/gpt-4o")
    fuzzy = _fuzzy_score("gpt4o", "openai/gpt-4o")
    assert exact > fuzzy > 0
