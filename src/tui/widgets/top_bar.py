"""The navbar — brand · folder · model · 🛡️ mode · Σ tokens+cost · state · sound.

    ✻ jimmy · 📂 Jimmy-Code · gemini-3.5-flash-lite   🟡 Auto   Σ 17.3k · $0.0042  ⠹ 📖 Editing  ♪ 🔇 mute

Clickable:
    left side  → home
    🛡️ mode    → permission picker
    state chip → interrupt
    ♪          → play/stop

The Σ chip shows session tokens AND dollars (from the agent's
CostTracker via LiteLLM pricing); unknown-priced models simply show
tokens only.  Repaints are diffed — the chip never redraws unless a
value actually changed.

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

from ..kit.helpers import (
    SPINNER_FRAMES,
    compact_count,
    format_duration,
    jimmy,
    short_model,
)
from ..kit.sound import sound_chip_text
from ..kit.theme import THEME


class TopBar(Horizontal):
    """Status HUD — one row of real, live information."""

    def __init__(self, model: str) -> None:
        super().__init__(id="top-bar")

        # 🤖 Current model shown in the navbar.
        self.model_name = short_model(model)

        # 📂 Current working directory.
        self.cwd_path = Path.cwd()
        self.folder_name = self.cwd_path.name or "/"

        # 🎛️ HUD state.
        self._hud_state = "ready"  # ready|working|done|error|interrupted
        self._activity: str | None = None
        self._frame = 0

        # ⏱️ Timing.
        self._done_duration: float | None = None
        self._turn_started: float | None = None

        # 🔊 Used to avoid repainting sound chip unnecessarily.
        self._last_playing: bool | None = None

        # 💰 Last painted Σ values — the chip is diffed, not spammed.
        self._last_tokens: int | None = None
        self._last_cost: float | None = None
        self._last_delta: int = 0

        # ⏲️ Timers.
        self._spin_timer: Timer | None = None
        self._revert_timer: Timer | None = None
        self._sound_sync: Timer | None = None

        # 🧩 Cached child references.
        self._left: Static | None = None
        self._perm_chip: Static | None = None
        self._tokens_chip: Static | None = None
        self._state_chip: Static | None = None
        self._sound_chip: Static | None = None

        # 🛡️ Current permission label ("🟡 Auto").
        self._perm_label: str | None = None

    # ─────────────────────────────────────────────────────────────
    # layout
    # ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Static("", id="top-left")
        yield Static("", id="chip-perm")
        yield Static("", id="chip-tokens")
        yield Static("", id="chip-state")
        yield Static("", id="chip-sound")

    # ─────────────────────────────────────────────────────────────
    # brand
    # ─────────────────────────────────────────────────────────────

    def _brand_text(self) -> Text:
        """Brand + folder + short model using the live theme."""

        return Text.from_markup(
            f"[{THEME['accent']}]✻[/] [#e2e6f2]jimmy[/] "
            f"[#2a3148]·[/] [#7b8296]📂 {escape(self.folder_name)}[/] "
            f"[#2a3148]·[/] [#6e7690]{escape(self.model_name)}[/]"
        )

    # ─────────────────────────────────────────────────────────────
    # lifecycle
    # ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        try:
            self._left = self.query_one("#top-left", Static)
            self._perm_chip = self.query_one("#chip-perm", Static)
            self._tokens_chip = self.query_one("#chip-tokens", Static)
            self._state_chip = self.query_one("#chip-state", Static)
            self._sound_chip = self.query_one("#chip-sound", Static)
        except Exception:
            return

        if self._left is not None:
            self._left.update(self._brand_text())
            self._left.tooltip = f"{self.cwd_path} · click for home (ctrl+n)"

        if self._perm_chip is not None:
            self._perm_chip.tooltip = "permission mode — click to change (or /permissions)"

        if self._tokens_chip is not None:
            self._tokens_chip.tooltip = "session tokens & cost (input + output)"

        if self._state_chip is not None:
            self._state_chip.tooltip = "click to interrupt while working · press esc"

        if self._sound_chip is not None:
            self._sound_chip.tooltip = "sound — click or press ctrl+s"

        # 🛡️ Seed the permission chip from the session's mode.
        try:
            self._perm_label = jimmy(self).current_permission_label()
        except Exception:
            pass
        self._render_perm_chip()

        # 🔊 Keep sound state synchronized even when audio ends itself.
        self._sound_sync = self.set_interval(
            1.0,
            self._sync_sound_chip,
        )

        self._render_chips()

    def on_unmount(self) -> None:
        self._cancel_revert()

        if self._spin_timer is not None:
            self._spin_timer.stop()
            self._spin_timer = None

        if self._sound_sync is not None:
            self._sound_sync.stop()
            self._sound_sync = None

    # ─────────────────────────────────────────────────────────────
    # 🖱️ mouse
    # ─────────────────────────────────────────────────────────────

    def on_click(self, event: events.Click) -> None:
        control = event.control

        if control is None:
            return

        cid = control.id

        try:
            app = jimmy(self)
        except Exception:
            return

        if cid == "chip-sound":
            app.action_toggle_sound()

        elif cid == "top-left":
            app.action_home()

        elif cid == "chip-perm":
            app.action_permissions()  # 🛡️

        elif cid == "chip-state" and self._hud_state == "working":
            app.action_interrupt()

    # ─────────────────────────────────────────────
    # 🤖 model
    # ─────────────────────────────────────────────

    def set_model(self, model: str) -> None:
        """🤖 Update the displayed model after a live model switch."""

        self.model_name = short_model(model)

        if self._left is None:
            return

        try:
            self._left.update(self._brand_text())
        except errors.NoWidget:
            pass
        except Exception:
            # Decorative UI must never break the agent.
            pass

    # ─────────────────────────────────────────────
    # 🛡️ permission mode
    # ─────────────────────────────────────────────

    def set_permission_mode(self, label: str) -> None:
        """🛡️ Repaint the permission chip after a mode change."""

        self._perm_label = label
        self._render_perm_chip()

    def _render_perm_chip(self) -> None:
        if self._perm_chip is None or self._perm_label is None:
            return

        try:
            self._perm_chip.update(Text.from_markup(f"[#8a91a8]{escape(self._perm_label)}[/]"))
        except errors.NoWidget:
            pass
        except Exception:
            # Decorative UI must never break the agent.
            pass

    # ─────────────────────────────────────────────
    # 🔄 state transitions
    # ─────────────────────────────────────────────

    def set_thinking(self) -> None:
        self._cancel_revert()

        self._turn_started = time.monotonic()
        self._activity = None

        self._set_state("working")

    def set_activity(self, label: str | None) -> None:
        """Show what Jimmy is currently doing."""

        self._activity = label

        if self._hud_state == "working":
            self._render_chips()

    def set_ready(self) -> None:
        self._cancel_revert()

        self._activity = None
        self._turn_started = None
        self._done_duration = None
        self._last_delta = 0  # deltas only make sense mid-turn

        self._set_state("ready")

    def set_done(self, duration: float | None = None) -> None:
        """Show completion briefly, then return to ready."""

        self._done_duration = duration
        self._activity = None

        self._set_state("done")

        self._cancel_revert()
        self._revert_timer = self.set_timer(
            1.8,
            self.set_ready,
        )

    def set_error(self) -> None:
        self._cancel_revert()

        self._activity = None
        self._set_state("error")

    def set_interrupted(self) -> None:
        self._activity = None

        self._set_state("interrupted")

        self._cancel_revert()
        self._revert_timer = self.set_timer(
            2.4,
            self.set_ready,
        )

    # ─────────────────────────────────────────────
    # 🔊 refresh helpers
    # ─────────────────────────────────────────────

    def refresh_sound(self) -> None:
        """Refresh the sound chip after play/stop."""

        self._render_chips()

    def refresh_tokens(self) -> None:
        """Refresh token/cost totals."""

        self._render_chips()

    def refresh_theme(self) -> None:
        """Repaint navbar after a theme change."""

        if self._left is not None:
            try:
                self._left.update(self._brand_text())
            except errors.NoWidget:
                pass
            except Exception:
                pass

        self._render_chips()

    # ─────────────────────────────────────────────
    # internals
    # ─────────────────────────────────────────────
    # (one space was added above to keep the ruler honest)

    def _cancel_revert(self) -> None:
        if self._revert_timer is not None:
            self._revert_timer.stop()
            self._revert_timer = None

    def _sync_sound_chip(self) -> None:
        """Repaint sound chip only when play state changed."""

        try:
            playing = jimmy(self).sound.is_playing
        except Exception:
            return

        if playing != self._last_playing:
            self._render_chips()

    def _set_state(self, state: str) -> None:
        """Change state and manage spinner timer."""

        if state == "working":
            if self._spin_timer is None:
                self._spin_timer = self.set_interval(
                    0.08,
                    self._spin_tick,
                )

        elif self._spin_timer is not None:
            self._spin_timer.stop()
            self._spin_timer = None

        self._hud_state = state
        self._render_chips()

    def _spin_tick(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)

        self._render_chips()

    def _render_chips(self) -> None:
        """Guarded paint — navbar must never crash the agent."""

        if self._state_chip is None or self._sound_chip is None:
            return

        try:
            self._paint_chips()

        except errors.NoWidget:
            # Temporary Textual layout race.
            pass

        except Exception:
            # Decorative UI must never crash the agent.
            pass

    # ─────────────────────────────────────────────
    # Σ tokens + 💰 cost chip
    # ─────────────────────────────────────────────

    def _read_cost(self, app: object) -> float:
        """Read the session cost from the agent's CostTracker (safely)."""
        try:
            tracker = getattr(self.app.agent, "cost", None)
            value = getattr(tracker, "cost_usd", 0.0)
            cost = float(value)
            return cost if cost >= 0.0 else 0.0
        except Exception:
            return 0.0

    def _sigma_markup(self, tokens: int, cost: float, delta: int) -> Text:
        """Build the Σ chip: `Σ 17.3k · $0.0042` (+ live ± delta)."""
        accent2 = THEME.get("accent2", "#22d3ee")
        sigma = THEME.get("accent", "#fbbf24")

        parts = [
            f"[{sigma}]Σ[/]",
            f"[#7f8aa5]{compact_count(tokens)}[/]",
        ]

        if cost > 0:
            # 🪙 4 decimals under a cent, 2 above — no '$0.0000' spam.
            money = f"${cost:.4f}" if cost < 0.01 else f"${cost:.2f}"
            parts.append(f"[#34d399]{money}[/]")

        if delta:
            sign = "+" if delta > 0 else "−"
            color = "#34d399" if delta > 0 else "#fbbf24"
            parts.append(f"[#2a3148]·[/] [{color}]{sign}{compact_count(abs(delta))}[/]")

        return Text.from_markup("  ".join(parts))

    def _paint_chips(self) -> None:
        app = jimmy(self)

        # ─────────────────────────────────────────────
        # 🔊 sound state (read once, used below)
        # ─────────────────────────────────────────────

        try:
            self._last_playing = app.sound.is_playing
        except Exception:
            self._last_playing = False

        # ─────────────────────────────────────────────
        # Σ tokens + cost — diffed repaint
        # ─────────────────────────────────────────────

        tokens = self._tokens_chip

        if tokens is not None:
            total_in = int(getattr(app, "_total_in", 0))
            total_out = int(getattr(app, "_total_out", 0))
            total = total_in + total_out

            cost = self._read_cost(app)

            # 📈 Delta = tokens that arrived during the CURRENT turn
            #    (only meaningful while working).
            delta = 0
            if self._hud_state == "working":
                delta = total - self._last_tokens if self._last_tokens is not None else 0
                if delta < 0:
                    delta = 0

            # ♻️ Repaint only when something actually changed — the
            #    spinner ticks 12×/s and would otherwise spam layout.
            if (total, cost, delta) != (self._last_tokens, self._last_cost, self._last_delta):
                tokens.tooltip = (
                    f"{total_in:,} in · {total_out:,} out"
                    + (f" · ${cost:.4f}" if cost > 0 else "")
                    + " — this session"
                )
                tokens.update(self._sigma_markup(total, cost, delta))
                self._last_tokens = total
                self._last_cost = cost
                self._last_delta = delta

        # ─────────────────────────────────────────────
        # state
        # ─────────────────────────────────────────────

        chip = self._state_chip

        if chip is None:
            return

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

        # ─────────────────────────────────────────────
        # ♪ sound
        # ─────────────────────────────────────────────

        sound = self._sound_chip

        if sound is None:
            return

        sound.update(sound_chip_text(self._last_playing))
