"""The message timeline — always follows the latest output, with
drag-select-to-copy."""

from __future__ import annotations

import asyncio
import time

from textual import events
from textual.containers import VerticalScroll
from textual.widget import Widget

from ..kit.helpers import jimmy
from .messages import EmptyState


class ChatLog(VerticalScroll):
    """The message timeline.

    * ``append`` mounts a widget and pins to the bottom immediately.
    * ``pin`` is throttled so per-token streaming never floods layout.
    * Drag-select text → release copies it, with a confirmation toast.
    """

    PIN_THROTTLE = 0.03

    def __init__(self) -> None:
        super().__init__()
        self._last_pin = 0.0
        self._empty_state: EmptyState | None = None

    def compose(self) -> Any:
        self._empty_state = EmptyState()
        yield self._empty_state

    @property
    def is_empty(self) -> bool:
        return self._empty_state is not None

    def append(self, widget: Widget) -> None:
        if self._empty_state is not None:
            self._empty_state.remove()
            self._empty_state = None
        self.mount(widget)
        self.pin(force=True)

    def clear(self) -> None:
        self.remove_children()
        self._last_pin = 0.0
        self._empty_state = EmptyState()
        self.mount(self._empty_state)
        self.scroll_to(y=0, animate=False)

    def pin(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_pin < self.PIN_THROTTLE:
            return
        self._last_pin = now
        self.call_after_refresh(self.scroll_end, animate=False)

    # mouse-selection copy -------------------------------------------------

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.call_after_refresh(self._maybe_copy_selection)

    def _maybe_copy_selection(self) -> None:
        # ``selected_text`` may be a str property, a method, or absent.
        raw = getattr(self, "selected_text", None)
        try:
            if callable(raw):
                raw = raw()
        except Exception:
            raw = None
        if not isinstance(raw, str):
            return
        text = raw.strip()
        if not text:
            return
        app = jimmy(self)
        try:
            result = app.copy_to_clipboard(text)
        except Exception:
            app.notify("clipboard failed", severity="error", timeout=1.5)
            return
        if asyncio.iscoroutine(result):
            try:
                asyncio.get_running_loop().create_task(result)
            except RuntimeError:
                result.close()
        app.notify("✓ selection copied", timeout=1.2)
