"""Composer：粘贴清洗、↑/↓ 历史记录，以及斜杠命令弹窗（与缩减后的
COMMANDS 集 /model · /sound · /help · /quit 同步）。"""

from __future__ import annotations

from conftest import leave_home, settle, tui_test

from tui.kit.helpers import MAX_PASTE_CHARS
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
        assert app.composer._slash.is_open  # 保持打开状态 → Enter 运行它


@tui_test
async def test_help_opens_help_dialog(app) -> None:
    from tui.widgets.composer import HelpDialogScreen

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)

        for char in "/help":
            await pilot.press(char)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, HelpDialogScreen)

        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert not isinstance(app.screen, HelpDialogScreen)


@tui_test
async def test_multiline_paste_flattened(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        prompt = app.composer._prompt_input

        prompt.value = "line one\nline two\r\nline three"
        await pilot.pause()
        await pilot.pause()

        assert prompt.value == "line one line two line three"


@tui_test
async def test_absurd_paste_is_capped(app) -> None:
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await leave_home(app, pilot)
        prompt = app.composer._prompt_input

        prompt.value = "y" * (MAX_PASTE_CHARS + 10)
        await pilot.pause()
        await pilot.pause()

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
        assert app.composer._prompt_input.value == ""  # 草稿已恢复


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
