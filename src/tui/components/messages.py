"""Chat messages — one widget per speaker/state.

Every message follows the same two-part pattern (Claude Code style):

    ● jimmy              ← .marker   who's talking (color = identity)
      streamed reply…    ← .body     what they said, indented 2 cols

No bubbles, no borders — hierarchy comes from color and indentation.

Classes:
    Message          base — shared fade-in entrance
    UserMessage      echo of what the user typed (dim)
    AssistantMessage streamed reply, appended chunk by chunk
    ErrorMessage     something broke (red)
    SystemNote       quiet one-liner (cleared / no response / …)
    WelcomeMessage   first-run intro block
"""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, Static

# Hex colors here mirror the palette documented in styles/app.tcss.
_ACCENT = "#b392f8"
_MUTED = "#9a9daa"
_FAINT = "#5f626b"


class Message(Widget):
    """Base class for every chat message.

    Handles the entrance animation: messages mount at opacity 0
    (messages.tcss) and fade in from Python — Textual CSS has no
    `animate:` property, so the fade is driven by styles.animate().
    """

    _FADE_SECONDS = 0.22

    def on_mount(self) -> None:
        # Wait one refresh so the message is first painted at
        # opacity 0, then fade it in.
        self.call_after_refresh(self._fade_in)

    def _fade_in(self) -> None:
        self.styles.animate(
            "opacity",
            1.0,
            duration=self._FADE_SECONDS,
            easing="out_cubic",
        )


class UserMessage(Message):
    """What the user just typed — dim, like an echoed shell command."""

    def __init__(self, text: str) -> None:
        super().__init__(classes="msg msg-user")
        self._text = text

    def compose(self) -> ComposeResult:
        yield Label("❯ you", classes="marker")
        yield Static(escape(self._text), classes="body")


class AssistantMessage(Message):
    """A reply that streams in chunk by chunk."""

    def __init__(self) -> None:
        super().__init__(classes="msg msg-assistant")
        self._raw = ""  # unescaped buffer
        self._body: Static | None = None

    def compose(self) -> ComposeResult:
        yield Label("● jimmy", classes="marker")

    def append(self, chunk: str) -> None:
        """Add a chunk and re-render.

        The body is escaped so streamed text containing Rich markup
        characters (``[...]``) can't break rendering.
        """
        self._raw += chunk

        if self._body is None:
            self._body = Static(escape(self._raw), classes="body")
            self.mount(self._body)
        else:
            self._body.update(escape(self._raw))


class ErrorMessage(Message):
    """A failed turn — red marker, softened red body."""

    def __init__(self, exc: BaseException) -> None:
        super().__init__(classes="msg msg-error")
        self._exc = exc

    def compose(self) -> ComposeResult:
        yield Label("✕ error", classes="marker")
        yield Static(
            escape(f"{type(self._exc).__name__}: {self._exc}"),
            classes="body",
        )


class SystemNote(Message):
    """Quiet single-line system message (no body)."""

    def __init__(self, text: str) -> None:
        super().__init__(classes="msg msg-system")
        self._text = text

    def compose(self) -> ComposeResult:
        yield Label(f"✻ {escape(self._text)}", classes="marker")


class WelcomeMessage(Message):
    """Intro block shown at the top of a fresh chat."""

    def __init__(self, model: str) -> None:
        super().__init__(classes="msg msg-welcome")
        self._model = model

    def compose(self) -> ComposeResult:
        yield Static(self._content(), classes="welcome-body")

    def _content(self) -> str:
        return (
            f"[bold {_ACCENT}]✻ Jimmy[/]\n\n"
            f"[{_MUTED}]Your terminal-native AI coding assistant.[/]\n"
            f"[{_FAINT}]model · {escape(self._model)}[/]\n\n"
            f"[{_FAINT}]Type below and hit ↵ — Jimmy does the rest.[/]"
        )
