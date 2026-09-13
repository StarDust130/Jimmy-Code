"""ThinkingRow — animated placeholder while the model is working.

Replaced by a real AssistantMessage the moment the first token
of the reply arrives.

NOTE: implemented with a manual set_interval() animation instead of
textual.widgets.Spinner, because the installed Textual version
doesn't ship the Spinner widget (added in 0.86+).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Label

# Braille spinner frames — same glyph sequence Spinner("dots") uses.
_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_FRAME_RATE = 1 / 10  # seconds per frame


class ThinkingRow(Horizontal):
    """`⠋ jimmy is thinking…` — one animated row."""

    def __init__(self) -> None:
        super().__init__(classes="thinking-row")

        self._frame = 0
        self._timer = None

        self._glyph = Label(_FRAMES[0], classes="thinking-spinner")
        self._label = Label("jimmy is thinking…", classes="thinking-label")

    def compose(self) -> ComposeResult:
        yield self._glyph
        yield self._label

    def on_mount(self) -> None:
        # Tick the spinner ~10×/second.
        self._timer = self.set_interval(_FRAME_RATE, self._tick)

    def on_unmount(self) -> None:
        # Defensive: make sure the timer dies with the widget.
        if self._timer is not None:
            self._timer.stop()

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(_FRAMES)
        self._glyph.update(_FRAMES[self._frame])
