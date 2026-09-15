"""Home screen — the launch hero (wordmark, waves, starfield, prompt)."""

from __future__ import annotations

import time
from typing import Any, ClassVar

from rich.markup import escape
from rich.text import Text
from textual import errors, events
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Static

from ..kit.assets import (
    LOGO_WIDTH,
    TAGLINE,
    Starfield,
    flow_label,
    flow_logo,
    gradient_text,
    sparkle_line,
    wave_text,
)
from ..kit.helpers import format_duration, jimmy, keycap, pretty_pwd, short_model
from ..kit.sound import sound_chip_text
from ..kit.theme import THEME
from ..widgets.composer import PromptInput


class HomeScreen(Screen):
    """Launch hero — themed synthwave over a starfield.

    PERFORMANCE: when covered (command palette open on top), the ambient
    loop skips all painting.
    """

    HOME_HINTS: ClassVar[str] = (
        f"{keycap('↵', 'begin')}   [#2a3148]·[/]   {keycap('ctrl+s', 'sound')}"
    )

    def __init__(self, *, animated: bool = True) -> None:
        super().__init__()
        self.animated = animated
        self._started = 0.0
        self._revealed = False
        self._last_playing: bool | None = None
        self._anim_ticker: Timer | None = None
        self._brand: Static | None = None
        self._sparkles: Static | None = None
        self._logo: Static | None = None
        self._wave: Static | None = None
        self._sub: Static | None = None
        self._tagline: Static | None = None
        self._status: Static | None = None
        self._meta: Static | None = None
        self._prompt: PromptInput | None = None
        self._hints: Static | None = None
        self._top_sound: Static | None = None
        self._bottom_wave: Static | None = None

    def compose(self) -> Any:
        yield Starfield(id="home-stars")
        with Horizontal(id="home-top"):
            yield Static("", id="home-top-brand")
            yield Static("", id="home-top-sound")
        with Vertical(id="home-center"):
            with Vertical(id="hero"):
                yield Static("", id="home-sparkles")
                yield Static("", id="home-logo")
                yield Static("", id="home-wave")
                yield Static("", id="home-sub", classes="hidden-until")
                yield Static("", id="home-tagline", classes="hidden-until")
                yield Static("", id="home-status", classes="hidden-until")
                yield Static("", id="home-meta", classes="hidden-until")
                yield PromptInput(
                    placeholder="Give Jimmy a task…", id="home-prompt", classes="hidden-until"
                )
                yield Static("", id="home-hints", classes="hidden-until")
        yield Static("", id="home-bottom-wave")

    def on_mount(self) -> None:
        self._brand = self.query_one("#home-top-brand", Static)
        self._sparkles = self.query_one("#home-sparkles", Static)
        self._logo = self.query_one("#home-logo", Static)
        self._wave = self.query_one("#home-wave", Static)
        self._sub = self.query_one("#home-sub", Static)
        self._tagline = self.query_one("#home-tagline", Static)
        self._status = self.query_one("#home-status", Static)
        self._meta = self.query_one("#home-meta", Static)
        self._prompt = self.query_one("#home-prompt", PromptInput)
        self._hints = self.query_one("#home-hints", Static)
        self._top_sound = self.query_one("#home-top-sound", Static)
        self._bottom_wave = self.query_one("#home-bottom-wave", Static)

        self._top_sound.tooltip = "sound — click or press ctrl+s"
        self._paint_brand()

        self._started = time.monotonic() - (0.0 if self.animated else 99.0)
        self._anim_ticker = self.set_interval(1 / 20, self._home_frame)
        self._home_frame()

    def on_unmount(self) -> None:
        if self._anim_ticker is not None:
            self._anim_ticker.stop()
            self._anim_ticker = None

    # ctrl+h / ctrl+n toggle back to the workspace (intercepted at screen
    # level; PromptInput already handles them when its input is focused —
    # this covers focus anywhere else on home).
    def on_key(self, event: events.Key) -> None:
        if event.key in ("ctrl+h", "ctrl+n"):
            event.stop()
            event.prevent_default()
            jimmy(self).action_home()

    def _paint_brand(self) -> None:
        if self._brand is not None:
            try:
                self._brand.update(Text.from_markup(f"[{THEME['accent']}]✻[/] [#e2e6f2]jimmy[/]"))
            except errors.NoWidget:
                pass

    def on_click(self, event: events.Click) -> None:
        if getattr(event.control, "id", None) == "home-top-sound":
            jimmy(self).action_toggle_sound()

    # intro + ambient animation -------------------------------------------

    def _home_frame(self) -> None:
        try:
            if self.app.screen is not self:
                return  # covered by another screen — paint nothing
            self._home_frame_inner()
        except errors.NoWidget:
            pass
        except Exception:
            if self._anim_ticker is not None:
                self._anim_ticker.stop()
                self._anim_ticker = None

    def _home_frame_inner(self) -> None:
        t = time.monotonic() - self._started
        playing = jimmy(self).sound.is_playing

        if playing != self._last_playing:
            self._last_playing = playing
            if self._top_sound is not None:
                self._top_sound.update(sound_chip_text(playing))

        if self._sparkles is not None:
            self._sparkles.update(sparkle_line(t, LOGO_WIDTH))
        if self._logo is not None:
            self._logo.update(flow_logo(t))
        if self._wave is not None:
            self._wave.update(
                wave_text(
                    t,
                    LOGO_WIDTH,
                    amplitude=1.0 if playing else 0.45,
                    dim=not playing,
                )
            )
        if self._bottom_wave is not None:
            self._bottom_wave.update(
                wave_text(
                    t,
                    max(10, self.size.width),
                    amplitude=0.85 if playing else 0.4,
                    dim=not playing,
                )
            )

        if self._revealed:
            return

        if t >= 0.30 and self._sub is not None:
            self._sub.remove_class("hidden-until")
            self._sub.update(
                Text("───  ", style="#2a3148")
                + flow_label("C  O  D  E", t)
                + Text("  ───", style="#2a3148")
            )

        if t >= 0.40 and self._tagline is not None:
            self._tagline.remove_class("hidden-until")
            shown = min(len(TAGLINE), int((t - 0.40) / 0.013) + 1)
            if shown >= len(TAGLINE):
                self._tagline.update(gradient_text(TAGLINE, "#a78bfa", "#22d3ee"))
            else:
                cursor = "▌" if int(t * 6) % 2 == 0 else " "
                self._tagline.update(
                    Text.from_markup(f"{escape(TAGLINE[:shown])}[#22d3ee]{cursor}[/]")
                )

        if t >= 0.50 and self._status is not None:
            self._status.remove_class("hidden-until")
            marks = (
                (0.50, "[#fbbf24]⚡ tools[/]"),
                (0.62, "[#c084fc]🧠 context[/]"),
                (0.74, "[#22d3ee]💾 session[/]"),
            )
            parts = [markup for threshold, markup in marks if t >= threshold]
            self._status.update(Text.from_markup("  [#2a3148]·[/]  ".join(parts)))

        if t >= 0.82 and self._meta is not None:
            self._meta.remove_class("hidden-until")
            self._meta.update(self._build_status())

        if t >= 0.95:
            self._reveal_all()

    def _reveal_all(self) -> None:
        if self._revealed:
            return
        self._revealed = True
        t = time.monotonic() - self._started

        if self._sub is not None:
            self._sub.remove_class("hidden-until")
            self._sub.update(
                Text("───  ", style="#2a3148")
                + flow_label("C  O  D  E", t)
                + Text("  ───", style="#2a3148")
            )
        if self._tagline is not None:
            self._tagline.remove_class("hidden-until")
            self._tagline.update(gradient_text(TAGLINE, "#a78bfa", "#22d3ee"))
        if self._status is not None:
            self._status.remove_class("hidden-until")
            self._status.update(
                Text.from_markup(
                    "[#fbbf24]⚡ tools[/]  [#2a3148]·[/]  "
                    "[#c084fc]🧠 context[/]  [#2a3148]·[/]  "
                    "[#22d3ee]💾 session[/]"
                )
            )
        if self._meta is not None:
            self._meta.remove_class("hidden-until")
            self._meta.update(self._build_status())
        if self._hints is not None:
            self._hints.remove_class("hidden-until")
            self._hints.update(Text.from_markup(self.HOME_HINTS))
        if self._prompt is not None:
            self._prompt.remove_class("hidden-until")
            self._prompt.focus()

    def refresh_status(self) -> None:
        """Repaint brand + meta + sound chip (theme switch, sound toggle)."""
        self._paint_brand()
        try:
            if self._meta is not None:
                self._meta.update(self._build_status())
            if self._top_sound is not None:
                self._top_sound.update(sound_chip_text(jimmy(self).sound.is_playing))
        except errors.NoWidget:
            pass

    def _build_status(self) -> Text:
        app = jimmy(self)
        playing = app.sound.is_playing
        if playing:
            sound_part = f"[{THEME['accent']}]♪[/] [#fda4af]🔇[/] [#8a91a8]mute[/]"
        else:
            sound_part = "[#3a4157]♪[/] [#8a91a8]sound[/]"
        from ..kit.theme import app_version

        meta = (
            f"[#565d73]v{app_version()}[/]  [#2a3148]·[/]  "
            f"[#4b5163]{escape(pretty_pwd())}[/]  [#2a3148]·[/]  "
            f"[#7b8296]{escape(short_model(str(app.provider.model)))}[/]  "
            f"[#2a3148]·[/]  {sound_part}"
        )
        if getattr(app, "_busy", False):
            elapsed = format_duration(time.monotonic() - app._turn_start)
            meta += f"  [#2a3148]·[/]  [#fbbf24]✻[/] [#8a91a8]working {elapsed}[/]"
        return Text.from_markup(meta)
