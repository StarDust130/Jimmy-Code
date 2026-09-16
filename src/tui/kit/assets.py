"""Home-screen visuals: wordmark, waves, sparkles.

Every painter reads the live theme, so 🎨 theme switches repaint the hero
instantly.  All functions are pure (time in → Text out).

NOTE: the full-screen Starfield was removed on purpose — the hero is
cleaner without it.  If any other module still imports ``Starfield``
from here, delete that import.
"""

from __future__ import annotations

import math

from rich.text import Text

from .helpers import WAVE_GLYPHS, blend_hex
from .theme import THEME, flow

# ── wordmark ──────────────────────────────────────────────────────────
# Hand-drawn block glyphs, 10 rows tall — bigger, cleaner, always aligned.

_GLYPHS: dict[str, tuple[str, ...]] = {
    "J": (
        "     ██╗",
        "     ██║",
        "     ██║",
        "██   ██║",
        "╚█████╔╝",
        " ╚════╝",
    ),
    "I": (
        "██╗",
        "██║",
        "██║",
        "██║",
        "██║",
        "╚═╝",
    ),
    "M": (
        "███╗   ███╗",
        "████╗ ████║",
        "██╔████╔██║",
        "██║╚██╔╝██║",
        "██║ ╚═╝ ██║",
        "╚═╝     ╚═╝",
    ),
    "Y": (
        "██╗   ██╗",
        "╚██╗ ██╔╝",
        " ╚████╔╝ ",
        "  ╚██╔╝  ",
        "   ██║   ",
        "   ╚═╝   ",
    ),
}


def _wordmark(
    word: str = "JIMMY",
) -> tuple[tuple[str, ...], tuple[tuple[int, int], ...]]:
    """Assemble block letters into equal-width rows.

    Returns ``(rows, letter_spans)`` where ``letter_spans[i]`` is the
    ``(start, end)`` column range of letter *i* inside every assembled
    row — used by the per-letter reveal animation.
    """
    letters: list[tuple[str, ...]] = []
    spans: list[tuple[int, int]] = []
    cursor = 0

    for ch in word:
        rows = _GLYPHS[ch]
        width = max(len(r) for r in rows)
        rows = tuple(r.ljust(width) for r in rows)
        letters.append(rows)
        spans.append((cursor, cursor + width))
        cursor += width + 2

    height = max(len(letter) for letter in letters)

    rows_out = tuple(
        "  ".join(letter[row] if row < len(letter) else " " * len(letter[0]) for letter in letters)
        for row in range(height)
    )

    return rows_out, tuple(spans)


LOGO_ROWS, _LETTER_SPANS = _wordmark("JIMMY")
LOGO_WIDTH: int = len(LOGO_ROWS[0])
TAGLINE = "terminal-native AI coding agent"


def flow_logo(t: float) -> Text:
    """JIMMY wordmark — letters pop in one by one and flash on landing.

    Ambient: theme flow palette + bevel + chromatic letter edges + a
    traveling light band.  All rows are always rendered (blanks
    reserved ahead of time) so the intro never reflows the layout.
    """
    last_row = len(LOGO_ROWS) - 1
    band = ((t * 13.0) % (LOGO_WIDTH + 40.0)) - 20.0

    text = Text()

    for r, row in enumerate(LOGO_ROWS):
        if r:
            text.append("\n")

        for c, ch in enumerate(row):
            if ch == " ":
                text.append(" ")
                continue

            # Locate the letter this cell belongs to → its reveal time.
            li = 0
            appear = 0.0

            for si, (s, e) in enumerate(_LETTER_SPANS):
                if s <= c < e:
                    li = si
                    appear = 0.08 + si * 0.085 + r * 0.030
                    break

            if t < appear:
                text.append(" ")
                continue

            color = flow(t * 0.07 + c * 0.010 + r * 0.04)

            # Bevel — bright top edge, dark bottom edge.
            if r == 0:
                color = blend_hex(color, "#f6f4ff", 0.26)
            elif r == last_row:
                color = blend_hex(color, "#0a0d18", 0.30)

            # Chromatic letter edges — cool left, warm right.
            s, e = _LETTER_SPANS[li]
            if c == s:
                color = blend_hex(color, "#22d3ee", 0.20)
            elif c == e - 1:
                color = blend_hex(color, "#f472b6", 0.20)

            # Landing flash — each letter pops white, then settles.
            age = t - appear
            if age < 0.22:
                color = blend_hex(
                    color,
                    "#ffffff",
                    0.65 * (1.0 - age / 0.22),
                )

            # Traveling light band.
            d = abs(c - band)
            if d < 1.0:
                color = "#ffffff"
            elif d < 4.5:
                color = blend_hex(
                    color,
                    "#f5f2ff",
                    0.70 * (1.0 - d / 4.5),
                )

            text.append(ch, style=f"bold {color}")

    return text


def shimmer_text(
    text: str,
    t: float,
    c1: str = "#a78bfa",
    c2: str = "#22d3ee",
) -> Text:
    """A gentle flowing gradient along static text (finished tagline)."""
    out = Text()
    n = max(1, len(text) - 1)

    for i, ch in enumerate(text):
        f = 0.5 + 0.5 * math.sin(i * 0.22 - t * 1.1)
        out.append(ch, style=blend_hex(c1, c2, f))

    return out


def sparkle_line(t: float, width: int) -> Text:
    """A single twinkling accent line above the wordmark."""
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
            out.append(
                ch,
                style=f"bold {flow(t * 0.06 + idx * 0.09)}",
            )
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


def wave_text(
    t: float,
    count: int,
    amplitude: float = 1.0,
    dim: bool = False,
) -> Text:
    """An animated equalizer wave, ``count`` cells wide — theme-colored."""
    start = THEME["accent"]
    end = THEME["accent2"]
    text = Text()

    for i in range(count):
        w1 = (math.sin(t * 4.6 + i * 0.55) + 1) / 2
        w2 = (math.sin(t * 1.9 + i * 0.23) + 1) / 2
        level = ((w1 * 0.65 + w2 * 0.35) ** 1.4) * amplitude

        idx = min(
            len(WAVE_GLYPHS) - 1,
            int(level * (len(WAVE_GLYPHS) - 1) + 0.5),
        )

        color = blend_hex(
            start,
            end,
            i / max(1, count - 1),
        )

        if dim:
            color = blend_hex(color, "#232838", 0.55)

        text.append(WAVE_GLYPHS[idx], style=color)

    return text
