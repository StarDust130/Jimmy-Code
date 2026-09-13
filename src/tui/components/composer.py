"""Composer — the input area at the bottom of the screen.

Two parts:
    #prompt          the rounded, Claude-style input box
    #composer-hints  dim cheat-sheet line right beneath it
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label

HINTS = "↵ send   ·   ctrl+l clear   ·   esc interrupt"


class Composer(Vertical):
    """Everything the user types into lives here."""

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="Ask Jimmy to build, debug, or explain code…",
            id="prompt",
        )
        yield Label(HINTS, id="composer-hints")

    def focus_input(self) -> None:
        """Put the cursor back in the box (call after any action)."""
        self.query_one("#prompt", Input).focus()
