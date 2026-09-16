"""ctrl+p palette: root commands, search filter, shortcuts view,
theme live-apply, and every close path."""

from __future__ import annotations

from typing import cast

from conftest import FakeClick, leave_home, scrim_click, tui_test
from textual import events

from tui.kit.theme import THEME, THEME_ORDER
from tui.screens.palette import CommandPaletteScreen


async def open_palette(app, pilot) -> CommandPaletteScreen:
    await pilot.press("ctrl+p")
    await pilot.pause()
    await pilot.pause()
    screen = app.screen
    assert isinstance(screen, CommandPaletteScreen)
    return screen


@tui_test
async def test_palette_lists_all_commands(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        screen = await open_palette(app, pilot)

        labels = [entry["label"] for entry in screen._entries]
        assert "Keyboard Shortcuts" in labels
        assert any(label.startswith("Theme") for label in labels)
        assert "Go home" in labels
        assert "Copy last prompt + reply" in labels
        assert "Copy whole chat" in labels
        assert "Sound play / stop" in labels
        assert "Clear chat timeline" in labels
        assert "Close menu" in labels


@tui_test
async def test_palette_search_filters_and_enter_opens_view(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        screen = await open_palette(app, pilot)

        for char in "theme":
            await pilot.press(char)
        await pilot.pause()
        assert [entry["label"] for entry in screen._entries] == ["Theme · violet"]

        await pilot.press("enter")
        await pilot.pause()
        assert screen._mode == "themes"


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
