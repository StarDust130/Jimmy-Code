"""ChatLog — scrolling conversation transcript."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widget import Widget


class ChatLog(VerticalScroll):
    """The conversation transcript."""

    can_focus = False

    def append(
        self,
        message: Widget,
    ) -> Widget:
        self.mount(message)
        self.scroll_end(animate=False)
        return message

    def pin(self) -> None:
        self.scroll_end(animate=False)

    def clear(self) -> None:
        for child in list(self.children):
            child.remove()
