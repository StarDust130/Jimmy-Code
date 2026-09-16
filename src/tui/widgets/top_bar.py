"""The navbar — brand · folder · model · Σ tokens (red) · state · sound.

    ✻ jimmy · 📂 Jimmy-Code · gemini-3.5-flash-lite   Σ 17.3k  ⠹ 📖 Editing  ♪ 🔇 mute

Clickable: left side → home · state chip → interrupt · ♪ → play/stop.
This widget is decorative chrome: every paint path is guarded, so a
chip glitch can never crash an agent turn.
"""

from __future__ import annotations

import time
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual import errors, events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.timer import Timer
from textual.widgets import Static

from ..kit.helpers import SPINNER_FRAMES, compact_count, format_duration, jimmy, short_model
from ..kit.sound import sound_chip_text
from ..kit.theme import THEME


class TopBar(Horizontal):
    """Status HUD — one row of real, live information."""

    def __init__(self, model: str) -> None:
        super().__init__(id="top-bar")
        self.model_name = short_model(model)
        self.cwd_path = Path.cwd()
        self.folder_name = self.cwd_path.name or "/"

        self._hud_state = "ready"  # ready|working|done|error|interrupted
        self._activity: str | None = None  # current tool label while working
        self._frame = 0  # spinner frame index
        self._done_duration: float | None = None
        self._turn_started: float | None = None
        self._last_playing: bool | None = None

        self._spin_timer: Timer | None = None  # runs only while working
        self._revert_timer: Timer | None = None  # done/interrupted → ready
        self._sound_sync: Timer | None = None  # keeps ♪ chip honest

        # Cached child refs (bound in on_mount, after compose).
        self._left: Static | None = None
        self._tokens_chip: Static | None = None
        self._state_chip: Static | None = None
        self._sound_chip: Static | None = None

    # layout ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("", id="top-left")
        yield Static("", id="chip-tokens")
        yield Static("", id="chip-state")
        yield Static("", id="chip-sound")

    def _brand_text(self) -> Text:
        """Brand + folder + short model — accent follows the live theme."""
        return Text.from_markup(
            f"[{THEME['accent']}]✻[/] [#e2e6f2]jimmy[/] "
            f"[#2a3148]·[/] [#7b8296]📂 {escape(self.folder_name)}[/] "
            f"[#2a3148]·[/] [#6e7690]{escape(self.model_name)}[/]"
        )

    def on_mount(self) -> None:
        try:
            self._left = self.query_one("#top-left", Static)
            self._tokens_chip = self.query_one("#chip-tokens", Static)
            self._state_chip = self.query_one("#chip-state", Static)
            self._sound_chip = self.query_one("#chip-sound", Static)
        except Exception:
            return  # children not queryable yet — _render_chips will no-op

        if self._left is not None:
            self._left.update(self._brand_text())
            self._left.tooltip = f"{self.cwd_path} · click for home (ctrl+n)"
        if self._tokens_chip is not None:
            self._tokens_chip.tooltip = "session tokens (input + output)"
        if self._state_chip is not None:
            self._state_chip.tooltip = "click to interrupt while working · press esc"
        if self._sound_chip is not None:
            self._sound_chip.tooltip = "sound — click or press ctrl+s"

        # Keep the ♪ chip honest even when the song ends on its own.
        self._sound_sync = self.set_interval(1.0, self._sync_sound_chip)
        self._render_chips()

    def on_unmount(self) -> None:
        self._cancel_revert()
        if self._spin_timer is not None:
            self._spin_timer.stop()
            self._spin_timer = None
        if self._sound_sync is not None:
            self._sound_sync.stop()
            self._sound_sync = None

    # mouse ──────────────────────────────────────────────────────────────

    def on_click(self, event: events.Click) -> None:
        control = event.control
        if control is None:
            return
        cid = control.id
        app = jimmy(self)
        if cid == "chip-sound":
            app.action_toggle_sound()
        elif cid == "top-left":
            app.action_home()
        elif cid == "chip-state" and self._hud_state == "working":
            app.action_interrupt()

    # state transitions (called by JimmyApp during a turn) ───────────────

    def set_thinking(self) -> None:
        self._cancel_revert()
        self._turn_started = time.monotonic()
        self._set_state("working")

    def set_activity(self, label: str | None) -> None:
        """Show what jimmy is doing right now (e.g. '📖 Editing x.ts')."""
        self._activity = label
        if self._hud_state == "working":
            self._render_chips()

    def set_ready(self) -> None:
        self._cancel_revert()
        self._activity = None
        self._set_state("ready")

    def set_done(self, duration: float | None = None) -> None:
        """Tiny completion celebration: ✓ done (n s) → ready shortly."""
        self._done_duration = duration
        self._activity = None
        self._set_state("done")
        self._revert_timer = self.set_timer(1.8, self.set_ready)

    def set_error(self) -> None:
        self._cancel_revert()
        self._activity = None
        self._set_state("error")

    def set_interrupted(self) -> None:
        self._activity = None
        self._set_state("interrupted")
        self._revert_timer = self.set_timer(2.4, self.set_ready)

    def refresh_sound(self) -> None:
        """Called right after the user plays/stops sound."""
        self._render_chips()

    def refresh_tokens(self) -> None:
        """Called after token totals change (each reply, /clear)."""
        self._render_chips()

    def refresh_theme(self) -> None:
        """Repaint brand + chips after a theme switch (live recolor)."""
        if self._left is not None:
            try:
                self._left.update(self._brand_text())
            except errors.NoWidget:
                pass
            except Exception:
                pass
        self._render_chips()

    # internals ──────────────────────────────────────────────────────────

    def _cancel_revert(self) -> None:
        if self._revert_timer is not None:
            self._revert_timer.stop()
            self._revert_timer = None

    def _sync_sound_chip(self) -> None:
        """Repaint the ♪ chip only when play state actually changed."""
        try:
            playing = jimmy(self).sound.is_playing
        except Exception:
            return
        if playing != self._last_playing:
            self._render_chips()

    def _set_state(self, state: str) -> None:
        # The spinner timer only runs while actually working (no idle CPU).
        if state == "working":
            if self._spin_timer is None:
                self._spin_timer = self.set_interval(0.08, self._spin_tick)
        elif self._spin_timer is not None:
            self._spin_timer.stop()
            self._spin_timer = None
        self._hud_state = state
        self._render_chips()

    def _spin_tick(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        self._render_chips()

    def _render_chips(self) -> None:
        """Guarded paint — the navbar is decorative, it must never raise."""
        if self._state_chip is None or self._sound_chip is None:
            return  # not mounted yet — on_mount will render
        try:
            self._paint_chips()
        except errors.NoWidget:
            pass  # transient layout race — the next tick will repaint
        except Exception:
            pass  # chrome glitch — never crash the app over it

    def _paint_chips(self) -> None:
        app = jimmy(self)

        # Σ session tokens (red) — reads live totals.
        self._last_playing = app.sound.is_playing
        tokens = self._tokens_chip
        if tokens is not None:
            total_in = getattr(app, "_total_in", 0)
            total_out = getattr(app, "_total_out", 0)
            tokens.tooltip = f"{total_in:,} in · {total_out:,} out — this session"
            tokens.update(
                Text.from_markup(f"[#F5C451]Σ[/] [#F5C451]{compact_count(total_in + total_out)}[/]")
            )

        # State chip: working spinner / done / error / interrupted / ready.
        chip = self._state_chip
        assert chip is not None
        if self._hud_state == "working":
            elapsed = ""
            if self._turn_started is not None:
                elapsed = format_duration(time.monotonic() - self._turn_started)
            glyph = SPINNER_FRAMES[self._frame]
            doing = self._activity or "working"
            chip.update(
                Text.from_markup(
                    f"[#fbbf24]{glyph}[/] [#d5dae8]{escape(doing)}[/]  [#565d73]{elapsed}[/]"
                )
            )
        elif self._hud_state == "done":
            extra = ""
            if self._done_duration is not None:
                extra = f"  [#565d73]{format_duration(self._done_duration)}[/]"
            chip.update(Text.from_markup(f"[#34d399]✓[/] [#8a91a8]done[/]{extra}"))
        elif self._hud_state == "error":
            chip.update(Text.from_markup("[#fb7185]✕[/] [#fb7185]error[/]"))
        elif self._hud_state == "interrupted":
            chip.update(Text.from_markup("[#fbbf24]⏹[/] [#8a91a8]interrupted[/]"))
        else:
            chip.update(Text.from_markup("[#34d399]●[/] [#565d73]ready[/]"))

        # ♪ chip: playing → mute action shown · stopped → play offered.
        sound = self._sound_chip
        assert sound is not None
        sound.update(sound_chip_text(self._last_playing))
