"""ChatLog — the scrolling conversation transcript.

Owns all message lifecycle helpers (append / clear / pin / welcome)
so the rest of the app never touches mount/scroll directly.
"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widget import Widget

from .messages import WelcomeMessage


class ChatLog(VerticalScroll):
    """The conversation lives here."""

    # The composer always owns the cursor — the transcript is for
    # reading, not focusing.
    can_focus = False

    def append(self, message: Widget) -> Widget:
        """Mount one message and pin the view to the bottom."""
        self.mount(message)
        self.scroll_end(animate=False)
        return message

    def pin(self) -> None:
        """Scroll to the newest content (call while streaming)."""
        self.scroll_end(animate=False)

    def clear(self) -> None:
        """Remove every message — the container itself stays."""
        for child in list(self.children):
            child.remove()

    def show_welcome(self, *, model: str) -> None:
        """Fresh-chat intro block."""
        self.append(WelcomeMessage(model))
