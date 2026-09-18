"""ctrl+p palette: root commands, search filter, shortcuts view,
theme live-apply, model-wizard handoff, and every close path.

The palette owns exactly FOUR commands (by design):
    Keyboard Shortcuts · Theme · Change model · Close menu
Navigation is ctrl+n / the wizard — there is no "Go home" entry.
"""

from __future__ import annotations

from typing import cast

from conftest import FakeClick, leave_home, scrim_click, tui_test
from textual import events

from tui.kit.theme import THEME, THEME_ORDER
from tui.screens.models import ModelScreen
from tui.screens.palette import CommandPaletteScreen


async def open_palette(app, pilot) -> CommandPaletteScreen:
    await pilot.press("ctrl+p")
    await pilot.pause()
    await pilot.pause()
    screen = app.screen
    assert isinstance(screen, CommandPaletteScreen)
    return screen


@tui_test
async def test_palette_lists_exactly_the_four_commands(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        screen = await open_palette(app, pilot)

        labels = [entry["label"] for entry in screen._entries]
        assert labels[0] == "Keyboard Shortcuts"
        assert any(label.startswith("Theme") for label in labels)
        assert any(label.startswith("Change model") for label in labels)
        assert labels[-1] == "Close menu"
        assert len(labels) == 4

        # "Go home" was removed by design — navigation is ctrl+n.
        assert "Go home" not in labels


@tui_test
async def test_palette_change_model_opens_wizard(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        screen = await open_palette(app, pilot)

        # find the Change model row and run it
        for entry in screen._entries:
            if entry["label"].startswith("Change model"):
                assert entry["action"] is not None
                entry["action"]()
                break
        else:
            pytest_fail("Change model row not found")

        await pilot.pause()
        await pilot.pause()

        # palette closed, wizard opened — the ONE model UI
        assert not isinstance(app.screen, CommandPaletteScreen)
        assert isinstance(app.screen, ModelScreen)


def pytest_fail(message: str) -> None:
    raise AssertionError(message)


@tui_test
async def test_palette_search_filters_commands(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        screen = await open_palette(app, pilot)

        for char in "theme":
            await pilot.press(char)
        await pilot.pause()

        labels = [entry["label"] for entry in screen._entries]
        assert len(labels) == 1
        assert labels[0].startswith("Theme")

        # unknown query → quiet empty state
        screen._rebuild("zzz-no-match")
        await pilot.pause()
        assert [e["label"] for e in screen._entries] == [] or screen._entries[0]["kind"] == "info"


@tui_test
async def test_palette_theme_up_down_applies_live(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        screen = await open_palette(app, pilot)
        screen._show_themes()
        await pilot.pause()
        assert screen._mode == "themes"
        assert len(screen._entries) == len(THEME_ORDER) + 1  # + back row

        await pilot.press("down")  # violet → ember, applied live
        await pilot.pause()
        assert THEME["name"] == "ember"

        await pilot.press("down")
        await pilot.pause()
        assert THEME["name"] == "frost"

        await pilot.press("escape")  # submenu → back to commands
        await pilot.pause()
        assert screen._mode == "commands"
        assert isinstance(app.screen, CommandPaletteScreen)


@tui_test
async def test_palette_shortcuts_view_esc_goes_back(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        screen = await open_palette(app, pilot)

        await pilot.press("enter")  # row 0 = Keyboard Shortcuts
        await pilot.pause()
        assert screen._mode == "shortcuts"
        info_rows = [e for e in screen._entries if e["kind"] == "info"]
        assert len(info_rows) >= len(CommandPaletteScreen.SHORTCUT_ROWS)

        await pilot.press("escape")  # back to commands, still open
        await pilot.pause()
        assert screen._mode == "commands"
        assert isinstance(app.screen, CommandPaletteScreen)

        await pilot.press("escape")  # commands → close
        await pilot.pause()
        await pilot.pause()
        assert not isinstance(app.screen, CommandPaletteScreen)


@tui_test
async def test_palette_esc_closes_from_commands(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        await open_palette(app, pilot)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert not isinstance(app.screen, CommandPaletteScreen)


@tui_test
async def test_palette_ctrl_p_toggles(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, CommandPaletteScreen)
        await pilot.press("ctrl+p")
        await pilot.pause()
        await pilot.pause()
        assert not isinstance(app.screen, CommandPaletteScreen)


@tui_test
async def test_palette_close_button(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        await open_palette(app, pilot)
        await pilot.click("#palette-close")
        await pilot.pause()
        await pilot.pause()
        assert not isinstance(app.screen, CommandPaletteScreen)


@tui_test
async def test_palette_click_outside_card_closes(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        screen = await open_palette(app, pilot)

        # Scrim click: control NOT inside #palette → must close.
        screen.on_click(cast(events.Click, scrim_click()))
        await pilot.pause()
        await pilot.pause()
        assert not isinstance(app.screen, CommandPaletteScreen)


@tui_test
async def test_palette_click_inside_card_stays_open(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        screen = await open_palette(app, pilot)

        from textual.widgets import Static

        title = screen.query_one("#palette-title", Static)
        screen.on_click(cast(events.Click, FakeClick(title)))
        await pilot.pause()
        assert isinstance(app.screen, CommandPaletteScreen)
