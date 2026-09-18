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
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Input, Static

from ..kit.helpers import MAX_PASTE_CHARS, jimmy, keycap
from ..kit.theme import THEME

# ══════════════════════════════════════════════════════════════════════
# ⌨️ SlashController — the ONE autocomplete implementation
# ══════════════════════════════════════════════════════════════════════


class SlashController:
    """Owns the slash-command popup for one (input, popup-container) pair.

    Used by BOTH the workspace composer and the home hero — one logic,
    zero duplication, zero name-collision bugs (the old in-Composer
    version crashed with ``'_index'`` vs ``_ac_index``).
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

        popup.display = False  # inline style; class toggles re-show it

    # ── state ─────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return bool(self._items) and self._popup.has_class("open")

    # ── driven by Input.Changed ───────────────────────────────────

    def on_text_changed(self, value: str) -> None:
        """Open / filter / close the popup for the current text."""
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
        """↑/↓ — popup navigation when open; history fallback when not.

        Returns True when the popup consumed the key."""
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
        """Tab — complete the highlighted command.  Returns True when
        the popup consumed the key."""
        if not (self.is_open and self._items):
            return False
        cmd = self._items[self._index]
        self._input.value = cmd
        self._input.cursor_position = len(cmd)
        return True

    def dismiss(self) -> bool:
        """Esc — close the popup, keep the typed text.  Returns True
        when the popup consumed the key."""
        if not self.is_open:
            return False
        self.close()
        return True

    def pick(self, index: int) -> None:
        """Mouse click on a suggestion row."""
        if not (0 <= index < len(self._items)):
            return
        cmd = self._items[index]
        self._input.value = cmd
        self._input.cursor_position = len(cmd)
        self.close()
        self._input.focus()

    def consume_submit(self) -> str | None:
        """Enter with popup open → the HIGHLIGHTED command (never a
        partial like '/cl').  Closes the popup; None when closed."""
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
    """One autocomplete suggestion row — clickable."""

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
    """Jimmy prompt input — home keys, popup keys, paste protection.

    ``ac_host`` is a SlashController (set by the owning screen after
    mount).  When set, Tab/↑/↓/Esc drive the popup; without one (never
    in this app) everything behaves like a plain Input.
    """

    # Subclass bindings override Input's inherited ones:
    #   * ctrl+h  → home (beats Input's "ctrl+h → delete_left")
    #   * tab     → autocomplete completion (standard in coding agents)
    #   * up/down → popup navigation when open, history when closed
    #   * escape  → dismiss popup when open, interrupt when closed
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

        # ↩️ set by the owning screen after mount (Composer / HomeScreen)
        self._ac_host: SlashController | None = None

    # ─────────────────────────────────────────────
    # actions (bound above)
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
        # Popup wasn't open → same behavior as the app escape binding.
        jimmy(self).action_interrupt()

    # ─────────────────────────────────────────────
    # Input sanitization + popup driving
    # ─────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        """Keep pasted input safe and drive the autocomplete popup."""
        if self._sanitizing:
            return

        value = event.value

        # Maximum prompt size.
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

        # Flatten multiline paste.
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

        # Large paste feedback.
        if len(value) - self._prev_len > 300:
            self.app.notify(
                f"📋 Pasted {len(value):,}",
                timeout=1.3,
            )

        self._prev_len = len(value)

        # 🔍 drive the slash popup on every change (both hosts).
        if self._ac_host is not None:
            self._ac_host.on_text_changed(value)


class Composer(Vertical):
    """Prompt + slash popup + shortcut rail + ↑/↓ history."""

    # 📋 slash commands — keep in sync with JimmyApp._run_command.
    COMMANDS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("/clear", "clear the chat timeline"),
        ("/home", "go to the home screen"),
        ("/model", "open the model picker (search every model)"),
        ("/theme", "cycle the accent theme"),
        ("/sound", "play / stop the startup sound"),
        ("/copy", "copy last prompt + reply"),
        ("/copyall", "copy the whole conversation"),
        ("/help", "show all commands"),
        ("/quit", "quit jimmy"),
    )

    HINTS_IDLE: ClassVar[str] = (
        f"{keycap('ctrl+h', '⌂ home')}   "
        f"{keycap('ctrl+p', '✦ commands')}   "
        f"{keycap('/', '⌘ slash menu')}   "
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

        # ⌨️ popup container (above the input) + controller.
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
    # 🧱 Layout
    # ─────────────────────────────────────────────

    def compose(self) -> Any:
        # popup sits ABOVE the input (rendered first in the column).
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
    # ↵ submit (popup-aware)
    # ─────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "prompt" or self._slash is None:
            return  # normal path — App handles the submit

        cmd = self._slash.consume_submit()
        if cmd is None:
            return  # popup closed → normal submit bubbles to App

        # Popup open → run the HIGHLIGHTED command; stop bubbling so
        # App never sees the partial text ('/cl').
        event.stop()
        self._prompt_input.value = ""
        self._prompt_input.cursor_position = 0

        if cmd.startswith("/"):
            jimmy(self)._run_command(cmd)

    # ─────────────────────────────────────────────
    # 📜 Prompt history
    # ─────────────────────────────────────────────

    def remember(self, text: str) -> None:
        """Remember a submitted prompt."""
        if not text:
            return

        if not self._history or self._history[-1] != text:
            self._history.append(text)

        self._hist_index = len(self._history)
        self._draft = ""

    def history_previous(self) -> None:
        """Move backward through prompt history."""
        if not self._history:
            return

        # Save the current draft before entering history.
        if self._hist_index == len(self._history):
            self._draft = self._prompt_input.value

        self._hist_index = max(
            0,
            self._hist_index - 1,
        )

        self._prompt_input.value = self._history[self._hist_index]
        self._prompt_input.cursor_position = len(self._prompt_input.value)

    def history_next(self) -> None:
        """Move forward through prompt history."""
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
    # 🪟 Public API
    # ─────────────────────────────────────────────

    def focus_input(self) -> None:
        """Focus the prompt."""
        self._prompt_input.focus()

    def clear_input(self) -> None:
        """Clear the prompt."""
        self._prompt_input.value = ""
        self._prompt_input.cursor_position = 0
        if self._slash is not None:
            self._slash.close()

    def set_busy(self, busy: bool) -> None:
        """Update prompt state and shortcut hints."""

        if busy:
            if self._slash is not None:
                self._slash.close()
            self._prompt_input.placeholder = "Jimmy is working — esc to interrupt"
            self.add_class("busy")

            markup = self.HINTS_BUSY

        else:
            self._prompt_input.placeholder = "Give Jimmy a task…  ( / for commands )"
            self.remove_class("busy")

            markup = self.HINTS_IDLE

        self._hints_line.update(Text.from_markup(markup))

    def flash_success(self) -> None:
        """Briefly show the success state."""
        self.add_class("celebrate")

        if self._celebrate_timer is not None:
            self._celebrate_timer.stop()

        self._celebrate_timer = self.set_timer(
            1.2,
            self._end_celebrate,
        )

    def _end_celebrate(self) -> None:
        """Remove the temporary success state."""
        self._celebrate_timer = None
        self.remove_class("celebrate")
