"""The composer: prompt input, paste handling, history, and shortcuts.

ctrl+N:
    Works when the terminal reports a distinct ctrl+N key event.

Ctrl+N:
    Reliable fallback for terminals that translate ctrl+N   into Backspace.

Important:
    Never treat ``backspace`` itself as ctrl+n. In many terminals,
    ctrl+n and Backspace use the same control code.
"""

from __future__ import annotations

from typing import Any, ClassVar

from rich.text import Text
from textual import events
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import Input, Static

from ..kit.helpers import MAX_PASTE_CHARS, jimmy, keycap


class PromptInput(Input):
    """Jimmy prompt input with shortcuts and paste protection."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._sanitizing = False
        self._prev_len = 0


    # ─────────────────────────────────────────────
    # Input sanitization
    # ─────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        """Keep pasted input safe and provide small feedback."""
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


class Composer(Vertical):
    """Prompt, compact shortcuts, and ↑/↓ command history."""

    HINTS_IDLE: ClassVar[str] = (
        f"{keycap('⌂ ctrl+N', 'home')}   "
        f"{keycap('✦ Ctrl+P', 'commands')}   "
        f"{keycap('▣ Ctrl+C', 'copy')}   "
        f"{keycap('⏻ Ctrl+Q', 'quit')}"
    )

    HINTS_BUSY: ClassVar[str] = (
        f"{keycap('esc', 'stop')}   [#F5C451]✻[/] [#8A91A8]Jimmy is working[/]"
    )

    def __init__(self) -> None:
        super().__init__(id="composer")

        self._prompt_input = PromptInput(
            placeholder="Give Jimmy a task…",
            id="prompt",
        )

        self._hints_line = Static(
            Text.from_markup(self.HINTS_IDLE),
            id="composer-hints",
        )

        self._celebrate_timer: Timer | None = None

        self._history: list[str] = []
        self._hist_index = 0
        self._draft = ""

    # ─────────────────────────────────────────────
    # Compose
    # ─────────────────────────────────────────────

    def compose(self) -> Any:
        """Render the prompt and shortcut rail."""
        yield self._prompt_input
        yield self._hints_line

    # ─────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────

    def on_unmount(self) -> None:
        """Stop timers when the composer is removed."""
        if self._celebrate_timer is not None:
            self._celebrate_timer.stop()
            self._celebrate_timer = None

    # ─────────────────────────────────────────────
    # Prompt history
    # ─────────────────────────────────────────────

    def on_key(self, event: events.Key) -> None:
        """Navigate prompt history with ↑ and ↓."""
        if event.key == "up":
            event.stop()
            event.prevent_default()
            self.history_previous()

        elif event.key == "down":
            event.stop()
            event.prevent_default()
            self.history_next()

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
    # Public API
    # ─────────────────────────────────────────────

    def focus_input(self) -> None:
        """Focus the prompt."""
        self._prompt_input.focus()

    def clear_input(self) -> None:
        """Clear the prompt."""
        self._prompt_input.value = ""
        self._prompt_input.cursor_position = 0

    def set_busy(self, busy: bool) -> None:
        """Update prompt state and shortcut hints."""

        if busy:
            self._prompt_input.placeholder = "Jimmy is working — esc to interrupt"
            self.add_class("busy")

            markup = self.HINTS_BUSY

        else:
            self._prompt_input.placeholder = "Give Jimmy a task…"
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
