"""The composer: prompt input, paste handling, ↑/↓ history, and a
slash-command autocomplete popup.

⌨️ Slash autocomplete (like every great coding agent):
    * typing  "/"     → shows ALL commands
    * typing  "/mo"   → filters to /model
    * ↑/↓             → navigate popup when open, history when closed
    * Tab             → complete the highlighted command
    * Enter           → run the highlighted command (even a prefix)
    * Esc             → dismiss popup, keeps typed text
    * click a row     → completes it

The SAME popup runs on the home screen — both hosts use the shared
SlashController, so there is exactly ONE implementation.

/help opens a real HelpDialogScreen (shortcuts · commands · contact).

Ctrl+H / Ctrl+N: home.  Ctrl+H needs an explicit BINDINGS override
because Textual's built-in Input binds "ctrl+h → delete_left"; subclass
bindings override inherited ones (documented behavior).

Ctrl+M reality check: on standard terminals ctrl+m is the SAME BYTE as
Enter (0x0d).  While typing it submits — nothing can change that.  The
model picker while typing is the slash menu:  /m + Tab + Enter.
ctrl+m still opens models when no input is focused, and always on
kitty-protocol terminals.
"""

from __future__ import annotations

from typing import Any, Callable, ClassVar

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Input, Static

from ..kit.helpers import MAX_PASTE_CHARS, jimmy, keycap
from ..kit.theme import THEME

# ══════════════════════════════════════════════════════════════════════
# ⌨️ SlashController — the ONE autocomplete implementation
# ══════════════════════════════════════════════════════════════════════


class SlashController:
    """拥有用于一对（输入框，弹窗容器）的斜杠命令弹窗。

    同时被工作区编写器和主屏幕英雄组件（hero）使用——只需一套逻辑，
    实现零重复，且没有命名冲突的 Bug。
    """

    def __init__(
        self,
        *,
        input_widget: Input,
        popup: Vertical,
        commands: tuple[tuple[str, str], ...],
        on_run: Callable[[str], None],
        fallback_up: Callable[[], None] | None = None,
        fallback_down: Callable[[], None] | None = None,
    ) -> None:
        self._input = input_widget
        self._popup = popup
        self._commands = commands
        self._on_run = on_run
        self._fallback_up = fallback_up
        self._fallback_down = fallback_down

        self._items: list[str] = []
        self._index = 0

        popup.display = False  # 行内样式；通过类名切换来重新显示它

    # ── state ─────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return bool(self._items) and self._popup.has_class("open")

    # ── driven by Input.Changed ───────────────────────────────────

    def on_text_changed(self, value: str) -> None:
        """为当前文本打开 / 过滤 / 关闭弹窗。"""
        if not value.startswith("/"):
            self.close()
            return

        query = value[1:].strip().lower()

        self._items = [
            cmd for cmd, _desc in self._commands if not query or cmd[1:].startswith(query)
        ]

        if not self._items:
            self.close()
            return

        self._index = 0
        self._render()

    # ── keyboard ──────────────────────────────────────────────────

    def move(self, delta: int) -> bool:
        """↑/↓ — 弹窗打开时进行导航；未打开时回退到历史记录。

        当弹窗消耗了该按键时，返回 True。"""
        if self.is_open and self._items:
            self._index = (self._index + delta) % len(self._items)
            self._render()
            return True
        if delta < 0 and self._fallback_up is not None:
            self._fallback_up()
        elif delta > 0 and self._fallback_down is not None:
            self._fallback_down()
        return False

    def complete(self) -> bool:
        """Tab — 自动补全高亮显示的命令。当弹窗消耗了该按键时，
        返回 True。"""
        if not (self.is_open and self._items):
            return False
        cmd = self._items[self._index]
        self._input.value = cmd
        self._input.cursor_position = len(cmd)
        return True

    def dismiss(self) -> bool:
        """Esc — 关闭弹窗，保留已输入的文本。当弹窗消耗了该按键时，
        返回 True。"""
        if not self.is_open:
            return False
        self.close()
        return True

    def pick(self, index: int) -> None:
        """鼠标点击某一行建议。"""
        if not (0 <= index < len(self._items)):
            return
        cmd = self._items[index]
        self._input.value = cmd
        self._input.cursor_position = len(cmd)
        self.close()
        self._input.focus()

    def consume_submit(self) -> str | None:
        """弹窗打开时按 Enter → 选中的命令（永远不会是像 '/cl' 这样
        的部分输入）。关闭弹窗；如果弹窗已关闭，则返回 None。"""
        if not (self.is_open and self._items):
            return None
        cmd = self._items[self._index]
        self.close()
        return cmd

    # ── rendering ─────────────────────────────────────────────────

    def close(self) -> None:
        self._items = []
        self._index = 0
        self._popup.remove_children()
        self._popup.remove_class("open")
        self._popup.display = False

    def _render(self) -> None:
        self._popup.remove_children()

        descriptions = dict(self._commands)
        accent = THEME["accent"]

        for i, cmd in enumerate(self._items):
            selected = i == self._index
            marker = f"[{accent}]›[/] " if selected else "  "
            row = ACRow(
                Text.from_markup(
                    f"{marker}[#9fb4ff]{escape(cmd)}[/]  "
                    f"[#565d73]{escape(descriptions.get(cmd, ''))}[/]"
                ),
                i,
                self,
            )
            if selected:
                row.add_class("selected")
            self._popup.mount(row)

        self._popup.add_class("open")
        self._popup.display = True


class ACRow(Static):
    """一行可点击的自动补全建议。"""

    def __init__(
        self,
        markup: Text,
        index: int,
        controller: SlashController,
    ) -> None:
        super().__init__(markup, classes="ac-row")
        self._index = index
        self._controller = controller

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self._controller.pick(self._index)


class PromptInput(Input):
    """Jimmy 提示输入框 — 包含 home 按键、弹窗按键和粘贴保护。

    ``ac_host`` 是一个 SlashController（由所属屏幕在挂载后设置）。
    设置后，Tab/↑/↓/Esc 将驱动弹窗；未设置时（在此应用中绝不会发生），
    所有行为都类似于普通的 Input。
    """

    # 子类绑定会覆盖 Input 继承的绑定：
    #   * ctrl+h  → home（胜过 Input 的 "ctrl+h → delete_left"）
    #   * tab     → 自动补全
    #   * up/down → 弹窗打开时为导航，关闭时为历史记录
    #   * escape  → 弹窗打开时关闭弹窗，关闭时中断
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+h", "go_home", show=False),
        Binding("tab", "ac_complete", show=False),
        Binding("up", "ac_move_up", show=False),
        Binding("down", "ac_move_down", show=False),
        Binding("escape", "ac_escape", show=False),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._sanitizing = False
        self._prev_len = 0

        # ↩️ 由所属屏幕在挂载后设置（Composer / HomeScreen）
        self._ac_host: SlashController | None = None

    # ─────────────────────────────────────────────
    # actions（在上面绑定）
    # ─────────────────────────────────────────────

    def action_go_home(self) -> None:
        jimmy(self).action_home()

    def action_ac_complete(self) -> None:
        if self._ac_host is not None:
            self._ac_host.complete()

    def action_ac_move_up(self) -> None:
        if self._ac_host is not None:
            self._ac_host.move(-1)

    def action_ac_move_down(self) -> None:
        if self._ac_host is not None:
            self._ac_host.move(1)

    def action_ac_escape(self) -> None:
        if self._ac_host is not None and self._ac_host.dismiss():
            return
        # 弹窗未打开 → 与应用级别的 escape 绑定行为相同。
        jimmy(self).action_interrupt()

    # ─────────────────────────────────────────────
    # 输入清洗 + 弹窗驱动
    # ─────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        """确保粘贴的输入安全，并驱动自动补全弹窗。"""
        if self._sanitizing:
            return

        value = event.value

        # 最大提示词大小。
        if len(value) > MAX_PASTE_CHARS:
            self._sanitizing = True

            try:
                self.value = value[:MAX_PASTE_CHARS]
                self.cursor_position = len(self.value)
            finally:
                self._sanitizing = False

            self.app.notify(
                f"⚠️ Input limited to {MAX_PASTE_CHARS:,}",
                severity="warning",
                timeout=1.8,
            )

            self._prev_len = MAX_PASTE_CHARS
            return

        # 拍平多行粘贴。
        if "\n" in value or "\r" in value:
            flattened = " ".join(value.split())

            self._sanitizing = True

            try:
                self.value = flattened
                self.cursor_position = len(flattened)
            finally:
                self._sanitizing = False

            self._prev_len = len(flattened)

            self.app.notify(
                "🧹 Pasted text cleaned",
                timeout=1.4,
            )
            return

        # 大量粘贴反馈。
        if len(value) - self._prev_len > 300:
            self.app.notify(
                f"📋 Pasted {len(value):,}",
                timeout=1.3,
            )

        self._prev_len = len(value)

        # 🔍 在每次更改时驱动斜杠弹窗（两个宿主）。
        if self._ac_host is not None:
            self._ac_host.on_text_changed(value)


class Composer(Vertical):
    """提示框 + 斜杠弹窗 + 快捷键栏 + ↑/↓ 历史记录。"""

    # 📋 斜杠命令 — 与 JimmyApp._run_command 同步。
    COMMANDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("/model", "open the model picker (search every model)"),
        ("/permissions", "permission mode · ask / auto / full access"),
        ("/sessions", "browse & resume past sessions"),
        ("/new", "start a fresh session"),
        ("/sound", "play / stop the startup sound"),
        ("/help", "shortcuts · commands · support"),
        ("/quit", "quit jimmy"),
    )

    HINTS_IDLE: ClassVar[str] = (
        f"{keycap('ctrl+h', '⌂ home')}   "
        f"{keycap('ctrl+p', '✦ commands')}   "
        f"{keycap('ctrl+c', '▣ copy')}   "
        f"{keycap('ctrl+q', '⏻ quit')}"
    )

    HINTS_BUSY: ClassVar[str] = (
        f"{keycap('esc', 'stop')}   [#F5C451]✻[/] [#8A91A8]Jimmy is working[/]"
    )

    def __init__(self) -> None:
        super().__init__(id="composer")

        self._prompt_input = PromptInput(
            placeholder="Give Jimmy a task…  ( / for commands )",
            id="prompt",
        )

        # ⌨️ 弹窗容器（在输入框上方）+ 控制器。
        self._ac_box: Vertical | None = None
        self._slash: SlashController | None = None

        self._hints_line = Static(
            Text.from_markup(self.HINTS_IDLE),
            id="composer-hints",
        )

        self._celebrate_timer: Timer | None = None

        self._history: list[str] = []
        self._hist_index = 0
        self._draft = ""

    # ─────────────────────────────────────────────
    # 🧱 布局
    # ─────────────────────────────────────────────

    def compose(self) -> Any:
        # 弹窗位于输入框上方（在列中最先渲染）。
        with Vertical(id="ac-popup"):
            pass

        yield self._prompt_input
        yield self._hints_line

    def on_mount(self) -> None:
        self._ac_box = self.query_one("#ac-popup", Vertical)

        self._slash = SlashController(
            input_widget=self._prompt_input,
            popup=self._ac_box,
            commands=self.COMMANDS,
            on_run=lambda cmd: jimmy(self)._run_command(cmd),
            fallback_up=self.history_previous,
            fallback_down=self.history_next,
        )
        self._prompt_input._ac_host = self._slash

    def on_unmount(self) -> None:
        if self._celebrate_timer is not None:
            self._celebrate_timer.stop()
            self._celebrate_timer = None

    # ─────────────────────────────────────────────
    # ↵ 提交（弹窗感知）
    # ─────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt" or self._slash is None:
            return  # 正常路径 — App 处理提交

        cmd = self._slash.consume_submit()
        if cmd is None:
            return  # 弹窗已关闭 → 正常提交冒泡到 App

        # 弹窗打开 → 运行高亮显示的命令；停止冒泡，以便 App
        # 永远看不到部分文本（如 '/mo'）。
        event.stop()
        self._prompt_input.value = ""
        self._prompt_input.cursor_position = 0

        if cmd.startswith("/"):
            jimmy(self)._run_command(cmd)

    # ─────────────────────────────────────────────
    # 📜 提示历史
    # ─────────────────────────────────────────────

    def remember(self, text: str) -> None:
        """记住一个已提交的提示词。"""
        if not text:
            return

        if not self._history or self._history[-1] != text:
            self._history.append(text)

        self._hist_index = len(self._history)
        self._draft = ""

    def history_previous(self) -> None:
        """向后浏览提示历史。"""
        if not self._history:
            return

        # 在进入历史记录前保存当前草稿。
        if self._hist_index == len(self._history):
            self._draft = self._prompt_input.value

        self._hist_index = max(
            0,
            self._hist_index - 1,
        )

        self._prompt_input.value = self._history[self._hist_index]
        self._prompt_input.cursor_position = len(self._prompt_input.value)

    def history_next(self) -> None:
        """向前浏览提示历史。"""
        if not self._history:
            return

        if self._hist_index >= len(self._history):
            return

        self._hist_index += 1

        if self._hist_index >= len(self._history):
            self._hist_index = len(self._history)
            self._prompt_input.value = self._draft
        else:
            self._prompt_input.value = self._history[self._hist_index]

        self._prompt_input.cursor_position = len(self._prompt_input.value)

    # ─────────────────────────────────────────────
    # 🪟 公共 API
    # ─────────────────────────────────────────────

    def focus_input(self) -> None:
        """聚焦提示框。"""
        self._prompt_input.focus()

    def clear_input(self) -> None:
        """清除提示框。"""
        self._prompt_input.value = ""
        self._prompt_input.cursor_position = 0
        if self._slash is not None:
            self._slash.close()

    def set_busy(self, busy: bool) -> None:
        """更新提示词状态和快捷键提示。"""

        if busy:
            if self._slash is not None:
                self._slash.close()
            self._prompt_input.placeholder = "Jimmy is working — esc to interrupt"
            self.add_class("busy")

            markup = self.HINTS_BUSY

        else:
            self._prompt_input.placeholder = "Give Jimmy a task… "
            self.remove_class("busy")

            markup = self.HINTS_IDLE

        self._hints_line.update(Text.from_markup(markup))

    def flash_success(self) -> None:
        """短暂显示成功状态。"""
        self.add_class("celebrate")

        if self._celebrate_timer is not None:
            self._celebrate_timer.stop()

        self._celebrate_timer = self.set_timer(
            1.2,
            self._end_celebrate,
        )

    def _end_celebrate(self) -> None:
        """移除临时的成功状态。"""
        self._celebrate_timer = None
        self.remove_class("celebrate")


# ══════════════════════════════════════════════════════════════════════
# ❓ /help — 帮助对话框（快捷键 · 命令 · 联系方式）
# ══════════════════════════════════════════════════════════════════════


class HelpDialogScreen(ModalScreen):
    """一个居中、具有主题感知能力的帮助卡片。

        ╭─ ❓ Jimmy Help ──────────────────────── esc ✕ ─╮
        │                                                │
        │  SHORTCUTS                                     │
        │   ↵  send · begin                              │
        │   ↑↓ prompt history / menu navigation          │
        │   …                                            │
        │                                                │
        │  SLASH COMMANDS                                │
        │   /model  open the model picker                │
        │   /sound  play / stop the startup sound        │
        │   /help   this dialog                          │
        │   /quit   quit jimmy                           │
        │                                                │
        │  MOUSE                                         │
        │   drag-select text to copy · click ✕ to close  │
        │                                                │
        │  💬 Questions? csy@gmail.com                   │
        ╰────────────────────────────────────────────────╯

    esc / ✕ 关闭它并将焦点恢复到下方的屏幕。
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close_help", "Close", priority=True),
    ]

    SHORTCUTS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("↵", "send · begin"),
        ("/", "slash menu (autocomplete in the prompt)"),
        ("↑ ↓", "prompt history / menu navigation"),
        ("esc", "interrupt jimmy / go back in menus"),
        ("ctrl+n", "home"),
        ("ctrl+p", "command menu"),
        ("ctrl+m", "model picker (outside the prompt)"),
        ("ctrl+c", "copy last prompt + reply (incl. tool calls)"),
        ("ctrl+a", "copy whole chat"),
        ("ctrl+l", "clear input line"),
        ("ctrl+s", "sound play / stop"),
        ("ctrl+q", "quit"),
        ("drag", "mouse-select text to copy"),
    )

    CONTACT = "csyadav0513@gmail.com"

    def compose(self) -> Any:
        with Vertical(id="help-card"):
            with Horizontal(id="help-head"):
                yield Static(
                    Text.from_markup(f"[{THEME['accent']}]❓[/] [#e2e6f2]Jimmy Help[/]"),
                    id="help-title",
                )
                yield Static(
                    Text.from_markup(keycap("esc", "close")),
                    id="help-esc",
                )
                yield Static("✕", id="help-close")

            yield Static("SHORTCUTS", classes="help-section")
            with Vertical(classes="help-block"):
                for key, desc in self.SHORTCUTS:
                    yield Static(
                        Text.from_markup(f"{keycap(key, '')}  [#aab2c7]{escape(desc)}[/]"),
                        classes="help-row",
                    )

            yield Static("SLASH COMMANDS", classes="help-section")
            with Vertical(classes="help-block"):
                for cmd, desc in Composer.COMMANDS:
                    yield Static(
                        Text.from_markup(f"[#9fb4ff]{escape(cmd)}[/]  [#aab2c7]{escape(desc)}[/]"),
                        classes="help-row",
                    )

            yield Static(
                Text.from_markup(
                    f"[#565d73]💬 Questions or bugs?  "
                    f"[#22d3ee]✉ {escape(self.CONTACT)}[/]  "
                    f"[#565d73]— we reply fast[/]"
                ),
                id="help-contact",
            )

            yield Static(
                "↑↓ scroll · esc close",
                id="help-foot",
            )

    def on_mount(self) -> None:
        close = self.query_one("#help-close", Static)
        close.tooltip = "close"

    def on_click(self, event: events.Click) -> None:
        control = event.control
        if control is None:
            return
        if getattr(control, "id", None) in ("help-close", "help-foot"):
            event.stop()
            self.action_close_help()
            return
        # 点击遮罩层（卡片外）→ 关闭
        node: Any = control
        while node is not None:
            if getattr(node, "id", None) == "help-card":
                return
            node = getattr(node, "parent", None)
        self.action_close_help()

    def action_close_help(self) -> None:
        self.dismiss()
