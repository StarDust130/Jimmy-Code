"""TopBar — the one-line header.

Left:   ✻ Jimmy · <model>
Right:  live state pill (● ready / ◌ thinking… / ✕ error)
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Label


class TopBar(Horizontal):
    """Minimal brand strip with a live status pill on the right."""

    def __init__(self, model: str) -> None:
        super().__init__()
        self._model = model
        self._state = Label("● ready", id="state")

    def compose(self) -> ComposeResult:
        yield Label("✻ Jimmy", id="brand")
        yield Label(f"· {self._model}", id="brand-model")
        yield Label("", id="top-spacer")  # flex spacer → pushes state right
        yield self._state

    def on_mount(self) -> None:
        self.set_ready()

    # ── state pill ───────────────────────────────────────

    def set_ready(self) -> None:
        self._set("● ready", "state-ready")

    def set_thinking(self) -> None:
        self._set("◌ thinking…", "state-thinking")

    def set_error(self) -> None:
        self._set("✕ error", "state-error")

    def set_interrupted(self) -> None:
        self._set("— interrupted", "state-interrupted")

    def _set(self, text: str, state_class: str) -> None:
        self._state.update(text)
        self._state.set_classes(f"state {state_class}")
