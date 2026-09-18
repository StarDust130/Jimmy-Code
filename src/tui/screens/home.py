"""Home screen — the launch hero (wordmark, waves, prompt, status bar)."""

from __future__ import annotations

import math
import os
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
    flow_label,
    flow_logo,
    shimmer_text,
    sparkle_line,
    wave_text,
)
from ..kit.helpers import blend_hex, jimmy, keycap
from ..kit.sound import sound_chip_text
from ..kit.theme import THEME
from ..widgets.composer import Composer, PromptInput, SlashController

_BRAND_SPIN: tuple[str, ...] = ("✻", "✽", "✳", "✢")
_PLACEHOLDERS: tuple[str, ...] = (
    "What should Jimmy build?",
    "fix the failing tests in src/",
    "explain this repo in one page",
    "write tests for the auth module",
    "refactor the composer widget",
    "add a dark-mode toggle to settings",
)

_SUB_AT: float = 0.95  # 'C O D E' appears
_TAG_AT: float = 1.05  # tagline typewriter starts
_TAG_SPEED: float = 0.014  # sec per char
_PROMPT_AT: float = 1.25  # prompt reveals + focuses
_HINTS_AT: float = 1.55  # key hints appear
_SKIP_BEFORE: float = 1.2  # any key before this skips the intro
_SCAN_DUR: float = 1.0  # boot scanline sweep duration


class HomeScreen(Screen):
    """Launch hero — synthwave wordmark, waves, living prompt.

    PERFORMANCE: when covered (command palette open on top), the ambient
    loop skips all painting.
    """

    HOME_HINTS: ClassVar[str] = (
        f"{keycap('🔊 Ctrl+S', 'sound/mute')}   "
        f"{keycap('✦ Ctrl+P', 'commands')}   "
        f"{keycap('⏻ Ctrl+Q', 'quit')}"
    )

    def __init__(self, *, animated: bool = True) -> None:
        super().__init__()

        self.animated = animated
        self._started = 0.0
        self._last_frame = 0.0
        self._revealed = False
        self._sub_on = False
        self._tag_on = False
        self._tag_done = False
        self._scan_done = False
        self._last_playing: bool | None = None
        self._last_value = ""
        self._excite = 0.0
        self._brand_step = -1
        self._ph_idx = 0
        self._ph_len = 0.0
        self._ph_dir = 1
        self._ph_hold = 0.0
        self._ph_last = ""
        self._anim_ticker: Timer | None = None

        self._brand: Static | None = None
        self._sparkles: Static | None = None
        self._logo: Static | None = None
        self._wave: Static | None = None
        self._sub: Static | None = None
        self._tagline: Static | None = None
        self._prompt: PromptInput | None = None
        self._hints: Static | None = None
        self._top_sound: Static | None = None
        self._scan: Static | None = None
        self._pwd: Static | None = None
        self._ver: Static | None = None
        self._bottom_wave: Static | None = None
        self._slash: SlashController | None = None

    # layout -------------------------------------------------------------

    def compose(self) -> Any:
        yield Static("", id="home-scan")

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

                yield PromptInput(
                    placeholder="What should Jimmy build?",
                    id="home-prompt",
                    classes="hidden-until",
                )

                yield Static("", id="home-hints", classes="hidden-until")

        with Horizontal(id="home-statusbar"):
            yield Static("", id="home-pwd")
            yield Static("", id="home-ver")

        yield Static("", id="home-bottom-wave")

    def on_mount(self) -> None:
        self._brand = self.query_one("#home-top-brand", Static)
        self._sparkles = self.query_one("#home-sparkles", Static)
        self._logo = self.query_one("#home-logo", Static)
        self._wave = self.query_one("#home-wave", Static)
        self._sub = self.query_one("#home-sub", Static)
        self._tagline = self.query_one("#home-tagline", Static)
        self._prompt = self.query_one("#home-prompt", PromptInput)
        self._hints = self.query_one("#home-hints", Static)
        self._top_sound = self.query_one("#home-top-sound", Static)
        self._scan = self.query_one("#home-scan", Static)
        self._pwd = self.query_one("#home-pwd", Static)
        self._ver = self.query_one("#home-ver", Static)
        self._bottom_wave = self.query_one("#home-bottom-wave", Static)

        self._top_sound.tooltip = "sound — click or press ctrl+s"
        self._pwd.tooltip = os.getcwd()
        self._ver.tooltip = "jimmy code"

        self._paint_brand()
        self._update_sound_chip()
        self._paint_status()

        self._started = time.monotonic() - (0.0 if self.animated else 99.0)
        self._anim_ticker = self.set_interval(1 / 20, self._home_frame)
        self._home_frame()

        # ⌨️ slash-command popup — same UX as the workspace composer.
        #    Mounted just above the home prompt, inside the hero.
        try:
            hero = self.query_one("#hero", Vertical)
            popup = Vertical(id="home-ac-popup")
            hero.mount(popup, before=self._prompt)
            self._slash = SlashController(
                input_widget=self._prompt,
                popup=popup,
                commands=Composer.COMMANDS,
                on_run=lambda cmd: jimmy(self)._run_command(cmd),
            )
            self._prompt._ac_host = self._slash
        except Exception:
            self._slash = None  # popup is cosmetic — never block home

    def on_unmount(self) -> None:
        if self._anim_ticker is not None:
            self._anim_ticker.stop()
            self._anim_ticker = None

    # painting -----------------------------------------------------------

    def _version_string(self) -> str:
        for attr in ("jimmy_version", "app_version", "version"):
            v = getattr(self.app, attr, None)
            if isinstance(v, str) and v:
                return v
        for dist in ("jimmy-code", "jimmy"):
            try:
                from importlib.metadata import version as _v

                return _v(dist)
            except Exception:
                continue
        return "dev"

    def _cwd_string(self) -> str:
        home = os.path.expanduser("~")
        cwd = os.getcwd()
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home) :]
        max_w = max(12, self.size.width - 20)
        if len(cwd) > max_w:
            cwd = "…" + cwd[-(max_w - 1) :]
        return cwd

    def _paint_status(self) -> None:
        try:
            if self._pwd is not None:
                self._pwd.update(
                    Text("◆ ", style="#39415c") + Text(self._cwd_string(), style="#566180")
                )
            if self._ver is not None:
                self._ver.update(Text(f"v{self._version_string()}", style="#3d4666"))
        except errors.NoWidget:
            pass

    def _paint_brand(self, spin: str = "✻") -> None:
        if self._brand is not None:
            try:
                self._brand.update(
                    Text.from_markup(
                        f"[{THEME['accent']}]{spin}[/] [#e2e6f2]jimmy[/] [#39415c]code[/]"
                    )
                )
            except (errors.NoWidget, KeyError, TypeError):
                pass

    def _update_sound_chip(self) -> None:
        try:
            if self._top_sound is not None:
                self._top_sound.update(sound_chip_text(jimmy(self).sound.is_playing))
        except errors.NoWidget:
            pass

    # interaction ----------------------------------------------------------

    def on_click(self, event: events.Click) -> None:
        if getattr(event.control, "id", None) == "home-top-sound":
            jimmy(self).action_toggle_sound()

    def on_key(self, event: events.Key) -> None:
        # any key skips the intro — never make people wait
        if (time.monotonic() - self._started) < _SKIP_BEFORE:
            self._started = time.monotonic() - 99.0

    def on_resize(self) -> None:
        self._paint_status()

    # ambient loop ---------------------------------------------------------

    def _home_frame(self) -> None:
        try:
            if self.app.screen is not self:
                return
            self._home_frame_inner()
        except errors.NoWidget:
            pass
        except Exception:
            if self._anim_ticker is not None:
                self._anim_ticker.stop()
                self._anim_ticker = None

    def _home_frame_inner(self) -> None:
        now = time.monotonic()
        t = now - self._started
        dt = 1 / 20 if self._last_frame <= 0 else min(0.25, now - self._last_frame)
        self._last_frame = now

        playing = jimmy(self).sound.is_playing
        if playing != self._last_playing:
            self._last_playing = playing
            self._update_sound_chip()

        # the page reacts to typing — a short energy pulse
        value = str(getattr(self._prompt, "value", "") or "")
        if value != self._last_value:
            self._last_value = value
            self._excite = 1.0
        if self._excite > 0.0:
            self._excite = max(0.0, self._excite - dt * 1.3)
        glow = self._excite

        self._brand_frame(t)
        self._placeholder_frame(dt)
        self._status_frame(t)

        if self._sparkles is not None:
            self._sparkles.update(sparkle_line(t + glow * 0.5, LOGO_WIDTH))

        if self._logo is not None:
            self._logo.update(flow_logo(t))

        amp = (1.0 if playing else 0.45) + 0.3 * glow
        if self._wave is not None:
            self._wave.update(wave_text(t, LOGO_WIDTH, amplitude=amp, dim=not playing))

        if self._bottom_wave is not None:
            self._bottom_wave.update(
                wave_text(
                    t,
                    max(10, self.size.width),
                    amplitude=(0.85 if playing else 0.4) + 0.25 * glow,
                    dim=not playing,
                )
            )

        self._scan_frame(t)
        self._reveal_frame(t)

    def _brand_frame(self, t: float) -> None:
        """The corner asterisk slowly turns — a quiet heartbeat."""
        step = int(t * 1.6) % len(_BRAND_SPIN)
        if step != self._brand_step:
            self._brand_step = step
            self._paint_brand(_BRAND_SPIN[step])

    def _status_frame(self, t: float) -> None:
        """The ◆ before the cwd breathes in the theme accent."""
        if self._pwd is None:
            return
        try:
            accent = THEME["accent"]
        except (KeyError, TypeError):
            accent = "#8b5cf6"
        pulse = 0.5 + 0.5 * math.sin(t * 1.8)
        out = Text("◆ ", style=blend_hex("#39415c", accent, 0.30 + 0.35 * pulse))
        out.append(self._cwd_string(), style="#566180")
        try:
            self._pwd.update(out)
        except errors.NoWidget:
            pass

    def _placeholder_frame(self, dt: float) -> None:
        """Typewriter placeholder cycling through task ideas.

        Pauses while the user has typed something; resumes when empty.
        """
        prompt = self._prompt
        if prompt is None:
            return
        if str(getattr(prompt, "value", "") or ""):
            return
        target = _PLACEHOLDERS[self._ph_idx]
        if self._ph_dir > 0:
            self._ph_len += dt / 0.05  # ~20 chars/sec
            if self._ph_len >= len(target):
                self._ph_len = float(len(target))
                self._ph_hold += dt
                if self._ph_hold >= 1.6:  # read a moment…
                    self._ph_hold = 0.0
                    self._ph_dir = -1
        else:
            self._ph_len -= dt / 0.025  # …delete faster
            if self._ph_len <= 0.0:
                self._ph_len = 0.0
                self._ph_dir = 1
                self._ph_idx = (self._ph_idx + 1) % len(_PLACEHOLDERS)
        shown = target[: int(self._ph_len)]
        if shown != self._ph_last:
            self._ph_last = shown
            try:
                prompt.placeholder = shown
            except Exception:
                pass

    def _scan_frame(self, t: float) -> None:
        """One-shot boot scanline sweeping down the screen."""
        if self._scan is None or self._scan_done:
            return
        if t >= _SCAN_DUR:
            self._scan_done = True
            try:
                self._scan.remove_class("on")
                self._scan.update("")
            except errors.NoWidget:
                pass
            return
        try:
            w = max(1, self.size.width)
            h = max(1, self.size.height)
            self._scan.add_class("on")
            self._scan.styles.offset = (0, min(h - 1, int(t / _SCAN_DUR * h)))
            line = Text()
            for x in range(w):
                g = math.sin(math.pi * x / max(1, w - 1)) ** 0.7
                line.append("─", style=blend_hex("#141a2c", "#7dd3fc", g))
            self._scan.update(line)
        except errors.NoWidget:
            pass

    def _reveal_frame(self, t: float) -> None:
        if not self._sub_on and t >= _SUB_AT and self._sub is not None:
            self._sub_on = True
            self._sub.remove_class("hidden-until")
        if self._sub_on and self._sub is not None:
            self._sub.update(
                Text("──  ", style="#2a3148")
                + flow_label("C  O  D  E", t - _SUB_AT)
                + Text("  ──", style="#2a3148")
            )

        if not self._tag_on and t >= _TAG_AT and self._tagline is not None:
            self._tag_on = True
            self._tagline.remove_class("hidden-until")
        if self._tag_on and self._tagline is not None:
            if not self._tag_done:
                shown = min(len(TAGLINE), int((t - _TAG_AT) / _TAG_SPEED) + 1)
                if shown >= len(TAGLINE):
                    self._tag_done = True
                else:
                    cursor = "▌" if int(t * 6) % 2 == 0 else " "
                    head = TAGLINE[: max(0, shown)]
                    self._tagline.update(Text.from_markup(f"{escape(head)}[#22d3ee]{cursor}[/]"))
            else:
                # finished typing → the gradient gently flows forever
                self._tagline.update(shimmer_text(TAGLINE, t))

        if not self._revealed and t >= _PROMPT_AT:
            self._reveal_all()

        if self._hints is not None and self._hints.has_class("hidden-until") and t >= _HINTS_AT:
            self._hints.remove_class("hidden-until")
            self._hints.update(Text.from_markup(self.HOME_HINTS))

    def _reveal_all(self) -> None:
        if self._revealed:
            return
        self._revealed = True
        if self._prompt is not None:
            self._prompt.remove_class("hidden-until")
            self._prompt.focus()

    def refresh_status(self) -> None:
        """Repaint brand + sound chip (theme switch, sound toggle)."""
        self._paint_brand()
        self._update_sound_chip()
        self._paint_status()

    def on_input_submitted(self, event: events.Input.Submitted) -> None:
        # ⌨️ slash popup open on home → run the highlighted command
        #    instead of submitting.
        if event.input.id == "home-prompt" and self._slash is not None and self._slash.is_open:
            event.stop()
            cmd = self._slash.consume_submit()
            if cmd:
                jimmy(self)._run_command(cmd)
