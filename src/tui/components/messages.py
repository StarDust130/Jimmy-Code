"""Chat messages."""

from __future__ import annotations

from rich.markdown import Markdown
from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, Static


class Message(Widget):
    """Base message."""

    def on_mount(self) -> None:
        self.call_after_refresh(self._fade_in)

    def _fade_in(self) -> None:
        self.styles.animate(
            "opacity",
            1.0,
            duration=0.18,
            easing="out_cubic",
        )


class UserMessage(Message):
    def __init__(
        self,
        text: str,
    ) -> None:
        super().__init__(classes="msg msg-user")
        self._text = text

    def compose(self) -> ComposeResult:
        yield Label(
            "❯ you",
            classes="marker",
        )

        yield Static(
            Text(self._text),
            classes="body",
        )


class AssistantMessage(Message):
    """Streaming assistant response."""

    def __init__(self) -> None:
        super().__init__(classes="msg msg-assistant")

        self._raw = ""

        self._body = Static(
            "",
            classes="body",
        )

    def compose(self) -> ComposeResult:
        yield Label(
            "● jimmy",
            classes="marker",
        )

        yield self._body

    def append(
        self,
        chunk: str,
    ) -> None:
        """Fast plain-text streaming."""
        if not chunk:
            return

        self._raw += chunk

        self._body.update(Text(self._raw))

    def finish_markdown(self) -> None:
        """Render Markdown only once after streaming ends."""
        self._body.update(Markdown(self._raw))


class ErrorMessage(Message):
    def __init__(
        self,
        exc: BaseException,
    ) -> None:
        super().__init__(classes="msg msg-error")
        self._exc = exc

    def compose(self) -> ComposeResult:
        yield Label(
            "✕ error",
            classes="marker",
        )

        yield Static(
            Text(f"{type(self._exc).__name__}: {self._exc}"),
            classes="body",
        )


class SystemNote(Message):
    def __init__(
        self,
        text: str,
    ) -> None:
        super().__init__(classes="msg msg-system")
        self._text = text

    def compose(self) -> ComposeResult:
        yield Label(
            f"✻ {self._text}",
            classes="marker",
        )
