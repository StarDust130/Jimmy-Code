"""Home-screen visuals: starfield, wordmark, waves, sparkles.

Every painter here reads the live theme, so 🎨 theme switches repaint
the hero instantly.  All functions are pure (time in → Text out).
"""

from __future__ import annotations

import math
import time
from typing import Any

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.strip import Strip
from textual.timer import Timer
from textual.widget import Widget

from .helpers import WAVE_GLYPHS, blend_hex
from .theme import THEME, flow

# ── starfield ──────────────────────────────────────────────────────────


def _star_tier(base: str, bright: str) -> tuple[Style, ...]:
    """Five brightness steps between two colors, parsed once at import."""
    return tuple(Style.parse(blend_hex(base, bright, step / 4)) for step in range(5))


_STAR_DIM = _star_tier("#1d2440", "#4a568c")
_STAR_MED = _star_tier("#2c3766", "#7d8fd6")
_STAR_BRIGHT = _star_tier("#6d5bb8", "#7fe7f7")


class Starfield(Widget):
    """Fullscreen twinkling starfield — the home screen backdrop.

    PERFORMANCE: when this widget's screen is not the top screen (the
    command palette covers us), the tick skips repainting entirely.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._born = time.monotonic()
        self._star_timer: Timer | None = None

    def on_mount(self) -> None:
        self._star_timer = self.set_interval(0.1, self._starfield_tick)

    def on_unmount(self) -> None:
        if self._star_timer is not None:
            self._star_timer.stop()
            self._star_timer = None

    def _starfield_tick(self) -> None:
        try:
            if self.app.screen is not self.screen:
                return  # covered by another screen — paint nothing
            self.refresh()
        except Exception:
            if self._star_timer is not None:
                self._star_timer.stop()
                self._star_timer = None

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if width <= 0:
            return Strip([])

        t = time.monotonic() - self._born
        drift = int(t * 1.4) % width
        segments: list[Segment] = []
        blanks = 0

        for x in range(width):
            sx = (x + drift) % width
            h = (sx * 374761393 + y * 668265263) & 0x7FFFFFFF
            h = ((h ^ (h >> 13)) * 1274126177) & 0x7FFFFFFF
            if h % 997 >= 26:
                blanks += 1
                continue
            if blanks:
                segments.append(Segment(" " * blanks))
                blanks = 0

            tier = h % 13
            glow = 0.5 + 0.5 * math.sin((h % 628) / 100.0 + t * (0.7 + (h % 5) * 0.31))
            if tier < 8:
                char, styles = "·", _STAR_DIM
            elif tier < 12:
                char, styles = "•", _STAR_MED
            else:
                char, styles = "✦", _STAR_BRIGHT
            segments.append(Segment(char, styles[int(glow * 4.999)]))

        if blanks:
            segments.append(Segment(" " * blanks))
        return Strip(segments)


# ── wordmark ───────────────────────────────────────────────────────────
# User-provided glyph table; rows are normalized to each letter's widest
# row at assembly time, so alignment is guaranteed.

_GLYPHS: dict[str, tuple[str, ...]] = {
    "J": (
        "████████",
        "    ███ ",
        "    ███ ",
        "    ███ ",
        "█   ███ ",
        " █████  ",
        "  ███   ",
    ),
    "I": (
        "████████",
        "   ███  ",
        "   ███  ",
        "   ███  ",
        "   ███  ",
        "   ███  ",
        "████████",
    ),
    "M": (
        "███   ███",
        "████ ████",
        "█████████",
        "███ █ ███",
        "███   ███",
        "███   ███",
        "███   ███",
    ),
    "Y": (
        "███   ███",
        " ███ ███ ",
        "  █████  ",
        "   ███   ",
        "   ███   ",
        "   ███   ",
        "   ███   ",
    ),
}

def _wordmark(word: str = "JIMMY") -> tuple[str, ...]:
    """Assemble block letters into equal-width rows (padded, aligned)."""
    letters: list[tuple[str, ...]] = []
    for ch in word:
        rows = _GLYPHS[ch]
        width = max(len(r) for r in rows)
        letters.append(tuple(r.ljust(width) for r in rows))
    height = max(len(letter) for letter in letters)
    return tuple(
        "  ".join(letter[row] if row < len(letter) else " " * len(letter[0]) for letter in letters)
        for row in range(height)
    )


LOGO_ROWS: tuple[str, ...] = _wordmark("JIMMY")
LOGO_WIDTH = len(LOGO_ROWS[0])
TAGLINE = "terminal-native AI coding agent"


def flow_logo(t: float) -> Text:
    """JIMMY wordmark — diagonal reveal, orbiting head, breathing glow.

    All rows are always rendered (blanks reserved ahead of time) so the
    intro never reflows the layout.
    """
    band = ((t * 22.0) % (LOGO_WIDTH + 26.0)) - 13.0
    text = Text()
    for r, row in enumerate(LOGO_ROWS):
        if r:
            text.append("\n")
        for c, ch in enumerate(row):
            if ch == " ":
                text.append(" ")
                continue
            if t < 0.10 + c * 0.011 + r * 0.05:  # diagonal reveal
                text.append(" ")
                continue
            color = flow(t * 0.09 + c * 0.012 + r * 0.05)

            d = abs(c - band)
            if d < 0.7:
                color = "#f8f6ff"  # orbiting bright head
            elif d < 3.0:
                color = blend_hex(color, "#f5f2ff", 1.0 - d / 3.0)
            else:
                breath = 0.5 + 0.5 * math.sin(t * 1.2 + c * 0.08)
                color = blend_hex(color, "#0b0e1a", 0.16 * (1.0 - breath))

            text.append(ch, style=f"bold {color}")
    return text


def sparkle_line(t: float, width: int) -> Text:
    """A twinkling accent line — sparkles breathe in the theme palette."""
    text = Text()
    for i in range(width):
        h = (i * 2654435761) & 0xFFFFFFFF
        phase = (h % 628) / 100.0
        speed = 0.9 + (h % 5) * 0.35
        s = 0.5 + 0.5 * math.sin(t * speed * 2.0 + phase)
        if s > 0.88:
            text.append("✦", style=flow((h % 997) / 997.0))
        elif s > 0.60:
            text.append("·", style="#4a568c")
        else:
            text.append(" ")
    return text


def flow_label(text: str, t: float) -> Text:
    """Per-letter animated flow palette — used for 'C  O  D  E'."""
    out = Text()
    idx = 0
    for ch in text:
        if ch != " ":
            out.append(ch, style=f"bold {flow(t * 0.06 + idx * 0.09)}")
            idx += 1
        else:
            out.append(ch)
    return out


def gradient_text(text: str, start: str, end: str) -> Text:
    """Static left-to-right color gradient (tagline, user prompts)."""
    out = Text()
    n = max(1, len(text) - 1)
    for i, ch in enumerate(text):
        out.append(ch, style=blend_hex(start, end, i / n))
    return out


def wave_text(t: float, count: int, amplitude: float = 1.0, dim: bool = False) -> Text:
    """An animated equalizer wave, ``count`` cells wide — theme-colored."""
    start = THEME["accent"]
    end = THEME["accent2"]
    text = Text()
    for i in range(count):
        w1 = (math.sin(t * 4.6 + i * 0.55) + 1) / 2
        w2 = (math.sin(t * 1.9 + i * 0.23) + 1) / 2
        level = ((w1 * 0.65 + w2 * 0.35) ** 1.4) * amplitude
        idx = min(len(WAVE_GLYPHS) - 1, int(level * (len(WAVE_GLYPHS) - 1) + 0.5))
        color = blend_hex(start, end, i / max(1, count - 1))
        if dim:
            color = blend_hex(color, "#232838", 0.55)
        text.append(WAVE_GLYPHS[idx], style=color)
    return text
