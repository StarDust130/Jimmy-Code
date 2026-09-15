"""Jimmy Code — terminal UI (presentation layer only).

Everything agent-related — LiteLLM streaming, tool execution, context
handling, token accounting and the event architecture — lives untouched
in ``jimmy.agent`` / ``jimmy.llm``.  This file only *renders* the event
stream: ``Agent.stream()`` yields ``AgentEvent`` objects, exactly as before.

Design language: retro arcade × synthwave × cyber terminal × premium dev tool.

Keyboard (on macOS the hints render ⌘ for ctrl)
    enter     send / begin              esc      interrupt a running turn
    ctrl+h    home (toggle; ctrl+n      ctrl+p   command palette (toggle)
              is a silent alias)        ctrl+c   copy last prompt + reply
    ctrl+l    clear the input line      ctrl+a   copy whole chat (when the
    ctrl+s    sound play / stop                  input isn't focused)
    ↑ / ↓     prompt history (unadvertised but always on)
    /clear    clear the chat · /copyall copy the whole conversation

Command palette (ctrl+p) — closes FIVE ways, all instant:
    esc (esc in a submenu goes BACK one level first) · ✕ header button ·
    "✕ Close menu" command · click outside the card · ctrl+p again.
    Theme submenu: ↑/↓ APPLIES the theme live as you move; ↵ returns to
    the command list.

CLOSE/Focus CONTRACT (why this version can't freeze or go dead)
    * Closing schedules ``app.pop_screen()`` via ``app.call_next`` — the
      screen stack is never mutated in the middle of a key/click dispatch,
      and the deprecated-prone ``Screen.dismiss()`` is never used.
    * One frame after the pop, focus is EXPLICITLY restored to the
      revealed screen's input (home prompt or composer).
    * A 1-second focus watchdog heals any state where no widget has
      focus while the app is idle — typing can never stay dead.
    * An app-side ``_palette_closing`` flag makes double-pops impossible.
    * No CSS transitions anywhere near the modal; the screens below stop
      painting while covered, so the modal always runs in a quiet loop.

Themes (live)
    violet → ember → frost → matrix — recolors the wordmark, sparkles,
    waves and navbar accents in real time.

Sound
    Plays ``public/song.mp3`` in full via whatever media CLI already exists
    on PATH (afplay / mpv / ffplay / mpg123) on an asyncio subprocess — it
    can never block the UI.  Labels are honest: "♪ 🔇 mute" while playing,
    "♪ sound" when stopped.

Stability rules this file follows (learned from real crashes)
    * No widget class defines a name Textual internals use (``_render`` is
      called by the layout engine while measuring ``height: auto`` rows;
      Screen carries selection APIs like ``clear_selection`` we must not
      shadow — palette methods use unique names instead).
    * Never read widget internals like ``Static.renderable`` — the palette
      repaints rows from its own row model with EXPLICIT colors on every
      segment (first-open can never be dark-on-dark).
    * Timer-driven ``update()`` calls go through ``_safe_update``.
"""

from __future__ import annotations

import asyncio
import math
import re
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from rich.markdown import Markdown as RichMarkdown
from rich.markup import escape
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import errors, events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.strip import Strip
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input, Static

from jimmy.agent import Agent, AgentEvent
from jimmy.llm.provider import LLMProvider

# ══════════════════════════════════════════════════════════════════════
# Constants & small helpers
# ══════════════════════════════════════════════════════════════════════

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"  # live rows (thinking / tools / navbar)
WAVE_GLYPHS = "▁▂▃▄▅▆▇█"  # equalizer waves (home + bottom strip)
MAX_PASTE_CHARS = 100_000  # absurd pastes are capped, never freeze
IS_MAC = sys.platform == "darwin"  # hints render ⌘ instead of "ctrl"


def format_duration(seconds: float) -> str:
    """Human duration: 84ms · 4.8s · 1m 02s."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining = int(seconds % 60)
    return f"{minutes}m {remaining:02d}s"


def compact_count(value: int) -> str:
    """17300 -> '17.3k' · 263 -> '263' · 2000000 -> '2M'."""

    def trim(x: float, suffix: str) -> str:
        return f"{x:.1f}".rstrip("0").rstrip(".") + suffix

    if value >= 1_000_000:
        return trim(value / 1_000_000, "M")
    if value >= 1_000:
        return trim(value / 1_000, "k")
    return str(value)


def clip(text: str, limit: int = 48) -> str:
    """Truncate long paths / commands / errors for tidy rows."""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def short_model(model: str) -> str:
    """'gemini/gemini-3.5-flash-lite' -> 'gemini-3.5-flash-lite'."""
    text = str(model).strip()
    return text.split("/")[-1] or text


def pretty_pwd() -> str:
    """The working directory with $HOME abbreviated to '~'."""
    cwd = str(Path.cwd())
    home = str(Path.home())
    return cwd.replace(home, "~", 1) if cwd.startswith(home) else cwd


def _blend_hex(start: str, end: str, t: float) -> str:
    """Linear-interpolate two '#rrggbb' colors (gradients / shimmer)."""
    t = max(0.0, min(1.0, t))
    a = (int(start[1:3], 16), int(start[3:5], 16), int(start[5:7], 16))
    b = (int(end[1:3], 16), int(end[3:5], 16), int(end[5:7], 16))
    return "#{:02x}{:02x}{:02x}".format(*(round(x + (y - x) * t) for x, y in zip(a, b)))


# ── Theme engine ───────────────────────────────────────────────────────

THEMES: dict[str, dict[str, Any]] = {
    "violet": {
        "stops": ("#a855f7", "#7c3aed", "#4f46e5", "#22d3ee", "#f472b6", "#a855f7"),
        "accent": "#c084fc",
        "accent2": "#22d3ee",
    },
    "ember": {
        "stops": ("#f59e0b", "#fb923c", "#f87171", "#f472b6", "#fbbf24", "#f59e0b"),
        "accent": "#fbbf24",
        "accent2": "#fb923c",
    },
    "frost": {
        "stops": ("#22d3ee", "#38bdf8", "#818cf8", "#a5f3fc", "#67e8f9", "#22d3ee"),
        "accent": "#22d3ee",
        "accent2": "#93c5fd",
    },
    "matrix": {
        "stops": ("#22c55e", "#4ade80", "#a3e635", "#10b981", "#86efac", "#22c55e"),
        "accent": "#34d399",
        "accent2": "#a3e635",
    },
}
THEME_ORDER: tuple[str, ...] = ("violet", "ember", "frost", "matrix")

THEME: dict[str, Any] = {
    "name": "violet",
    "accent": THEMES["violet"]["accent"],
    "accent2": THEMES["violet"]["accent2"],
}

CYBER: list[str] = []


def _rebuild_flow(stops: tuple[str, ...]) -> None:
    """Rebuild the 256-stop flow palette IN PLACE (references stay valid)."""
    palette: list[str] = []
    for i in range(256):
        pos = i / 255 * (len(stops) - 1)
        k = min(int(pos), len(stops) - 2)
        palette.append(_blend_hex(stops[k], stops[k + 1], pos - k))
    CYBER[:] = palette


_rebuild_flow(THEMES["violet"]["stops"])


def _flow(hue: float) -> str:
    """Map a hue in [0, 1) to the precomputed theme flow palette."""
    return CYBER[int((hue % 1.0) * 255) & 255]


_VERSION_CACHE: str | None = None


def _app_version() -> str:
    """Best-effort package version for the home status line."""
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        for package in ("jimmy", "jimmy-code"):
            try:
                from importlib.metadata import version

                _VERSION_CACHE = version(package)
                break
            except Exception:
                continue
        _VERSION_CACHE = _VERSION_CACHE or "0.1.0"
    return _VERSION_CACHE


def keycap(key: str, label: str) -> str:
    """A keyboard keycap in rich markup: `[ ctrl+h ] ⌂ home`.

    On macOS the ctrl prefix renders as ⌘ (user-facing convention).
    """
    shown = key
    if IS_MAC and shown.startswith("ctrl+"):
        shown = "⌘" + shown[len("ctrl+") :]
    return f"[#9fb4ff on #1a2242] {escape(shown)} [/][#565d73] {escape(label)}[/]"


def tool_display(tool_name: str, arguments: dict[str, Any]) -> tuple[str, str, str]:
    """Map a tool call to (emoji, action, detail) for readable rows."""
    mapping = {
        "read_file": ("📖", "Reading"),
        "read_files": ("📖", "Reading"),
        "write_file": ("📝", "Writing"),
        "write_files": ("📝", "Writing"),
        "edit_file": ("✏️", "Editing"),
        "edit_files": ("✏️", "Editing"),
        "search_files": ("🔍", "Searching"),
        "search_file": ("🔍", "Searching"),
        "grep": ("🔍", "Searching"),
        "list_files": ("📂", "Listing"),
        "glob": ("📂", "Listing"),
        "shell": ("▶️", "Running"),
        "run_shell": ("▶️", "Running"),
        "git_status": ("🌿", "Checking git"),
        "git_diff": ("🧾", "Checking diff"),
        "git_commit": ("📦", "Committing"),
    }

    icon, action = mapping.get(tool_name, ("🛠️", "Using"))

    detail = ""
    quoted = False
    for key in (
        "path",
        "file_path",
        "filepath",
        "filename",
        "paths",
        "files",
        "file_paths",
        "directory",
        "dir",
        "folder",
        "command",
        "cmd",
        "query",
        "pattern",
        "glob",
        "url",
        "message",
    ):
        value = arguments.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            detail = ", ".join(str(v) for v in value if str(v).strip())
        else:
            detail = str(value).strip()
        quoted = key in ("query", "pattern")
        if detail:
            break

    if detail and quoted:
        detail = f'"{detail}"'
    return icon, action, clip(detail)


# ── Error classification (the friendly error card) ────────────────────


def classify_error(error: BaseException) -> tuple[str, str, str]:
    """Map an exception to (icon, short title, human message)."""
    raw = str(error)
    low = f"{type(error).__name__}: {raw}".lower()

    code: int | None = getattr(error, "status_code", None)
    if code is None:
        match = re.search(r"\b([45]\d{2})\b", raw)
        code = int(match.group(1)) if match else None

    if code in (401, 403):
        return (
            "🔐",
            "API key problem",
            f"Jimmy's credentials were rejected (HTTP {code}). "
            "Check the API key and its permissions.",
        )
    if code == 429:
        return (
            "⏳",
            "Rate limited",
            "The provider is throttling requests (HTTP 429). Wait a little while, then retry.",
        )
    if code == 500:
        return ("⚠️", "Provider error", "The model provider hit an internal error (HTTP 500).")
    if code in (502, 503):
        return (
            "🔌",
            "Provider temporarily unavailable",
            f"The provider is temporarily unavailable (HTTP {code}) "
            "— this usually resolves on its own. Try again shortly.",
        )
    if "timeout" in low or "timed out" in low:
        return (
            "⏱️",
            "Request timed out",
            "The provider took too long to respond. Retry — it often works on the second try.",
        )
    if any(
        k in low for k in ("connection", "network", "unreachable", "getaddrinfo", "dns", "resolve")
    ):
        return ("🌐", "Network problem", "Couldn't reach the provider — check your connection.")
    return ("❌", "Something went wrong", clip(raw, 140) or type(error).__name__)


def _error_detail(error: BaseException) -> str:
    """Full traceback text for the expandable error view (capped)."""
    try:
        text = "".join(traceback.format_exception(type(error), error, error.__traceback__)).strip()
    except Exception:
        text = ""
    if not text:
        text = f"{type(error).__name__}: {error}"
    lines = text.splitlines()
    if len(lines) > 60:
        lines = lines[-60:]
        lines.insert(0, f"… ({len(lines)} more lines above)")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# Sound: full-track playback with honest play/stop semantics
# ══════════════════════════════════════════════════════════════════════


class SoundPlayer:
    """Fire-and-forget playback of ``public/song.mp3`` — the FULL track."""

    CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("afplay", ()),  # macOS
        ("mpv", ("--no-video", "--really-quiet")),  # linux/bsd
        ("ffplay", ("-nodisp", "-autoexit", "-loglevel", "quiet")),
        ("mpg123", ("-q",)),
    )

    def __init__(self) -> None:
        self._resolved = False
        self._command: tuple[str, ...] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task[None] | None = None
        self._starting = False

    @property
    def is_playing(self) -> bool:
        process = self._process
        if process is not None and process.returncode is None:
            return True
        return self._starting

    def locate_song(self) -> Path | None:
        here = Path(__file__).resolve()
        for base in (here.parents[2], here.parents[1], Path.cwd()):
            candidate = base / "public" / "song.mp3"
            if candidate.is_file():
                return candidate
        return None

    def play_startup(self) -> None:
        self.play(self.locate_song())

    def play(self, path: Path | None) -> None:
        if path is None:
            self._starting = False
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._starting = False
            return
        self.stop()
        self._starting = True
        self._task = loop.create_task(self._play(path))

    def stop(self) -> None:
        self._starting = False
        process = self._process
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        self._process = None

    async def _play(self, path: Path) -> None:
        if not self._resolved:
            self._resolved = True
            for name, arguments in self.CANDIDATES:
                found = await asyncio.to_thread(shutil.which, name)
                if found:
                    self._command = (found, *arguments)
                    break
        if self._command is None:
            self._starting = False
            return
        command = self._command
        try:
            self._process = await asyncio.create_subprocess_exec(
                *command,
                str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (OSError, ValueError):
            self._command = None
            self._starting = False
            return
        self._starting = False
        try:
            await self._process.wait()  # WHOLE song — no cutoff
        except asyncio.CancelledError:
            self.stop()
            raise


def sound_chip_text(playing: bool) -> Text:
    """One source of truth for every sound indicator (explicit colors)."""
    if playing:
        return Text.from_markup(f"[{THEME['accent']}]♪[/] [#fda4af]🔇[/] [#8a91a8]mute[/]")
    return Text.from_markup("[#3a4157]♪[/] [#8a91a8]sound[/]")


# ══════════════════════════════════════════════════════════════════════
# Home backdrop: starfield + themed wordmark + waves
# ══════════════════════════════════════════════════════════════════════


def _star_tier(base: str, bright: str) -> tuple[Style, ...]:
    """Five brightness steps between two colors, parsed once at import."""
    return tuple(Style.parse(_blend_hex(base, bright, step / 4)) for step in range(5))


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


# Block letters — user-provided glyph table, rows normalized per letter.
_GLYPHS: dict[str, tuple[str, ...]] = {
    "J": (
        "███████",
        "   ███ ",
        "   ███ ",
        "█  ███ ",
        " █████  ",
        "  ███   ",
    ),
    "I": (
        "███████",
        "  ███  ",
        "  ███  ",
        "  ███  ",
        "  ███  ",
        "███████",
    ),
    "M": (
        "███   ███",
        "████ ████",
        "██ ███ ██",
        "██  █  ██",
        "██     ██",
        "██     ██",
    ),
    "Y": (
        "███   ███",
        " ███ ███ ",
        "  █████  ",
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


def _flow_logo(t: float) -> Text:
    """JIMMY wordmark — diagonal reveal, orbiting head, breathing glow."""
    band = ((t * 22.0) % (LOGO_WIDTH + 26.0)) - 13.0
    text = Text()
    for r, row in enumerate(LOGO_ROWS):
        if r:
            text.append("\n")
        for c, ch in enumerate(row):
            if ch == " ":
                text.append(" ")
                continue
            if t < 0.10 + c * 0.011 + r * 0.05:
                text.append(" ")
                continue
            color = _flow(t * 0.09 + c * 0.012 + r * 0.05)

            d = abs(c - band)
            if d < 0.7:
                color = "#f8f6ff"
            elif d < 3.0:
                color = _blend_hex(color, "#f5f2ff", 1.0 - d / 3.0)
            else:
                breath = 0.5 + 0.5 * math.sin(t * 1.2 + c * 0.08)
                color = _blend_hex(color, "#0b0e1a", 0.16 * (1.0 - breath))

            text.append(ch, style=f"bold {color}")
    return text


def _sparkle_line(t: float, width: int) -> Text:
    """A twinkling accent line — sparkles breathe in the theme palette."""
    text = Text()
    for i in range(width):
        h = (i * 2654435761) & 0xFFFFFFFF
        phase = (h % 628) / 100.0
        speed = 0.9 + (h % 5) * 0.35
        s = 0.5 + 0.5 * math.sin(t * speed * 2.0 + phase)
        if s > 0.88:
            text.append("✦", style=_flow((h % 997) / 997.0))
        elif s > 0.60:
            text.append("·", style="#4a568c")
        else:
            text.append(" ")
    return text


def _flow_label(text: str, t: float) -> Text:
    """Per-letter animated flow palette — used for 'C  O  D  E'."""
    out = Text()
    idx = 0
    for ch in text:
        if ch != " ":
            out.append(ch, style=f"bold {_flow(t * 0.06 + idx * 0.09)}")
            idx += 1
        else:
            out.append(ch)
    return out


def _gradient_text(text: str, start: str, end: str) -> Text:
    """Static left-to-right color gradient (tagline, user prompts)."""
    out = Text()
    n = max(1, len(text) - 1)
    for i, ch in enumerate(text):
        out.append(ch, style=_blend_hex(start, end, i / n))
    return out


def _wave_text(t: float, count: int, amplitude: float = 1.0, dim: bool = False) -> Text:
    """An animated equalizer wave, ``count`` cells wide — theme-colored."""
    start = THEME["accent"]
    end = THEME["accent2"]
    text = Text()
    for i in range(count):
        w1 = (math.sin(t * 4.6 + i * 0.55) + 1) / 2
        w2 = (math.sin(t * 1.9 + i * 0.23) + 1) / 2
        level = ((w1 * 0.65 + w2 * 0.35) ** 1.4) * amplitude
        idx = min(len(WAVE_GLYPHS) - 1, int(level * (len(WAVE_GLYPHS) - 1) + 0.5))
        color = _blend_hex(start, end, i / max(1, count - 1))
        if dim:
            color = _blend_hex(color, "#232838", 0.55)
        text.append(WAVE_GLYPHS[idx], style=color)
    return text


# ══════════════════════════════════════════════════════════════════════
# Timeline widgets
# ══════════════════════════════════════════════════════════════════════


class _AnimatedRow(Static):
    """Base class for timer-animated timeline rows (crash-hardened)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._anim_timer: Timer | None = None

    def _start_anim(self, interval: float) -> None:
        if self._anim_timer is None:
            self._anim_timer = self.set_interval(interval, self._anim_tick)

    def _stop_anim(self) -> None:
        if self._anim_timer is not None:
            self._anim_timer.stop()
            self._anim_timer = None

    def _anim_tick(self) -> None:
        self._redraw()

    def _redraw(self) -> None:
        """Paint the current frame.  Overridden by subclasses."""

    def _safe_update(self, content: Any) -> None:
        try:
            self.update(content)
        except errors.NoWidget:
            self._stop_anim()
        except Exception:
            self._stop_anim()

    def on_unmount(self) -> None:
        self._stop_anim()


class ThinkingRow(_AnimatedRow):
    """`⠹ Thinking · 1.2s` — live line for the *current* model round."""

    def __init__(self, model: str, step: int) -> None:
        self.model_name = model
        self.step = step
        self.started = time.monotonic()
        self._frame = 0
        super().__init__("", classes="thinking-row")

    def on_mount(self) -> None:
        self.call_after_refresh(self._redraw)
        self._start_anim(0.1)

    def _redraw(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        elapsed = format_duration(time.monotonic() - self.started)
        suffix = "" if self.step <= 1 else f"  [#3a4157]round {self.step}[/]"
        self._safe_update(
            Text.from_markup(
                f"[{THEME['accent']}]{SPINNER_FRAMES[self._frame]}[/] "
                f"[#8a91a8]Thinking[/]  [#4b5163]{elapsed}[/]{suffix}"
            )
        )


class LiveToolStatus(_AnimatedRow):
    """One emoji-tagged tool line on the timeline."""

    def __init__(
        self, *, call_id: str, tool_name: str, icon: str, action: str, detail: str
    ) -> None:
        self.call_id = call_id
        self.tool_name = tool_name
        self.icon = icon
        self.action = action
        self.detail = detail
        self.started = time.monotonic()
        self._frame = 0
        super().__init__("", classes="live-tool-status")

    def on_mount(self) -> None:
        self.call_after_refresh(self._redraw)
        self._start_anim(0.1)

    def _label(self) -> str:
        return escape(f"{self.icon} {self.action}")

    def _detail_part(self) -> str:
        if not self.detail:
            return ""
        return f"  [#7b8296]{escape(self.detail)}[/]"

    def _redraw(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        elapsed = format_duration(time.monotonic() - self.started)
        self._safe_update(
            Text.from_markup(
                f"[{THEME['accent']}]{SPINNER_FRAMES[self._frame]}[/] "
                f"[#d5dae8]{self._label()}[/]{self._detail_part()}  "
                f"[#4b5163]{elapsed}[/]"
            )
        )

    def finish(self, latency: float) -> None:
        self._stop_anim()
        self._safe_update(
            Text.from_markup(
                f"[#34d399]✓[/] [#7f8aa5]{self._label()}[/]{self._detail_part()}  "
                f"[#34d399]{format_duration(latency)}[/]"
            )
        )

    def fail(self, error: BaseException) -> None:
        self._stop_anim()
        lines = str(error).strip().splitlines()
        reason = lines[0].strip() if lines and lines[0].strip() else type(error).__name__
        icon = classify_error(error)[0]
        self._safe_update(
            Text.from_markup(
                f"[#fb7185]✕[/] [#fda4af]{self._label()}[/]{self._detail_part()}  "
                f"[#fb7185]{icon} {escape(clip(reason, 40))}[/]"
            )
        )


class TurnSummary(_AnimatedRow):
    """The ONE per-turn digest — the only place token totals appear."""

    SPARK_COLORS = ("#c084fc", "#f472b6", "#22d3ee", "#93c5fd")

    def __init__(
        self, *, duration: float, input_tokens: int, output_tokens: int, tools: int, steps: int
    ) -> None:
        self._duration = duration
        self._input = input_tokens
        self._output = output_tokens
        self._tools = tools
        self._steps = steps
        self._frame = 0
        super().__init__("", classes="turn-summary")

    def on_mount(self) -> None:
        self.tooltip = "click to copy this exchange (prompt + reply)"
        self.call_after_refresh(self._redraw)
        self._start_anim(0.1)

    def _anim_tick(self) -> None:
        self._frame += 1
        if self._frame >= 6:
            self._stop_anim()
            self._frame = -1
        self._redraw()

    def _redraw(self) -> None:
        if self._frame < 0:
            spark = ""
        else:
            color = self.SPARK_COLORS[self._frame % len(self.SPARK_COLORS)]
            spark = f"[{color}]✦[/]  "

        parts = [f"[#93c5fd]{format_duration(self._duration)}[/]"]
        if self._input > 0:
            parts.append(f"[#93c5fd]{compact_count(self._input)}[/][#565d73] in[/]")
        if self._output > 0:
            parts.append(f"[#93c5fd]{compact_count(self._output)}[/][#565d73] out[/]")
        if self._tools > 0:
            plural = "s" if self._tools != 1 else ""
            parts.append(f"[#fbbf24]{self._tools}[/][#565d73] tool{plural}[/]")
        if self._steps > 1:
            parts.append(f"[#565d73]{self._steps}[/][#3a4157] rounds[/]")

        divider = "  [#2a3148]·[/]  "
        self._safe_update(Text.from_markup(f"{spark}{divider.join(parts)}  [#3a4157]⧉[/]"))

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.app.action_copy_last()


class PairDivider(Static):
    """A thin hairline after each completed prompt+reply pair."""

    def __init__(self) -> None:
        super().__init__("", classes="pair-divider")


class AssistantMessage(Vertical):
    """Assistant response block — streams plain text, then one Markdown
    upgrade (monokai code theme)."""

    STREAM_THROTTLE = 0.03

    def __init__(self) -> None:
        super().__init__(classes="msg msg-assistant")
        self._chunks: list[str] = []
        self._last_render = 0.0
        self._finished = False
        self._frame = 0
        self._body = Static("", classes="assistant-body")

    def compose(self) -> ComposeResult:
        yield self._body

    @property
    def raw_text(self) -> str:
        return "".join(self._chunks).strip()

    def _safe_body_update(self, content: Any) -> None:
        try:
            self._body.update(content)
        except errors.NoWidget:
            pass

    def append(self, chunk: str) -> None:
        if not chunk or self._finished:
            return
        self._chunks.append(chunk)
        now = time.monotonic()
        if now - self._last_render >= self.STREAM_THROTTLE:
            self._last_render = now
            self._render_stream()

    def _render_stream(self) -> None:
        self._frame += 1
        cursor_color = THEME["accent2"] if self._frame % 2 == 0 else THEME["accent"]
        text = escape("".join(self._chunks))
        self._safe_body_update(Text.from_markup(f"{text}[{cursor_color}]▍[/]"))

    def finish_markdown(self) -> None:
        if self._finished:
            return
        self._finished = True
        raw = self.raw_text
        if not raw:
            self.remove()
            return
        self._safe_body_update(RichMarkdown(raw, code_theme="monokai"))


class UserMessage(Static):
    """`❯ your prompt` — blue marker + blue→violet gradient prompt text."""

    def __init__(self, text: str) -> None:
        rendered = Text()
        rendered.append("❯ ", style="bold #60a5fa")
        rendered.append_text(_gradient_text(text, "#a5c8ff", "#c4b5fd"))
        super().__init__(rendered, classes="msg msg-user")


class ErrorCard(Vertical):
    """A friendly, classified error card with retry + expandable details."""

    def __init__(self, error: BaseException) -> None:
        icon, title, message = classify_error(error)
        self._icon = icon
        self._title = title
        self._message = message
        self._detail = _error_detail(error)
        super().__init__(classes="error-card")

    def compose(self) -> ComposeResult:
        yield Static(
            Text.from_markup(f"[#fb7185]✕[/]  [bold #fda4af]{self._icon} {escape(self._title)}[/]"),
            classes="err-title",
        )
        yield Static(Text.from_markup(f"[#c7cde4]{escape(self._message)}[/]"), classes="err-msg")
        with Horizontal(classes="err-actions"):
            yield Static(Text.from_markup("[#fbbf24]↻[/] [#e2e6f2] retry[/]"), id="err-retry")
            yield Static(Text.from_markup("[#565d73]⌄[/] [#8a91a8] details[/]"), id="err-details")
        yield Static(Text(self._detail), classes="err-detail")

    def on_mount(self) -> None:
        self.tooltip = "↻ retry runs the last prompt · ⌄ details shows the traceback"

    def on_click(self, event: events.Click) -> None:
        event.stop()
        cid = event.control.id
        if cid == "err-retry":
            if self.app.action_retry_last():
                try:
                    self.remove()
                except Exception:
                    pass
        elif cid == "err-details":
            detail = self.query_one(".err-detail")
            opened = detail.has_class("shown")
            detail.toggle_class("shown")
            label = self.query_one("#err-details", Static)
            if opened:
                label.update(Text.from_markup("[#565d73]⌄[/] [#8a91a8] details[/]"))
            else:
                label.update(Text.from_markup("[#8a91a8]⌃[/] [#8a91a8] details[/]"))


class SystemNote(Static):
    """Dim, italic one-liner for system events (cleared, interrupted…)."""

    def __init__(self, note: str) -> None:
        super().__init__(
            Text.from_markup(f"[#4b5163]· {escape(note)}[/]"),
            classes="msg-system",
        )


class EmptyState(Static):
    """Quiet welcome line before the first message — shows the full pwd."""

    def __init__(self) -> None:
        super().__init__(
            Text.from_markup(
                f"[{THEME['accent']}]✻[/] [#8a91a8]jimmy is ready[/]  "
                f"[#3a4157]·[/]  [#4b5163]{escape(pretty_pwd())}[/]\n"
                f"[#3a4157]describe a task · /help for commands[/]"
            ),
            classes="empty-state",
        )


class ChatLog(VerticalScroll):
    """The message timeline — always follows the latest output.

    Bonus: dragging a text selection and releasing copies it, with a
    toast to confirm.
    """

    PIN_THROTTLE = 0.03

    def __init__(self) -> None:
        super().__init__()
        self._last_pin = 0.0
        self._empty_state: EmptyState | None = None

    def compose(self) -> ComposeResult:
        self._empty_state = EmptyState()
        yield self._empty_state

    @property
    def is_empty(self) -> bool:
        return self._empty_state is not None

    def append(self, widget: Widget) -> None:
        if self._empty_state is not None:
            self._empty_state.remove()
            self._empty_state = None
        self.mount(widget)
        self.pin(force=True)

    def clear(self) -> None:
        self.remove_children()
        self._last_pin = 0.0
        self._empty_state = EmptyState()
        self.mount(self._empty_state)
        self.scroll_to(y=0, animate=False)

    def pin(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_pin < self.PIN_THROTTLE:
            return
        self._last_pin = now
        self.call_after_refresh(self.scroll_end, animate=False)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self.call_after_refresh(self._maybe_copy_selection)

    def _maybe_copy_selection(self) -> None:
        # ``selected_text`` may be a str property, a method, or absent.
        raw = getattr(self, "selected_text", None)
        try:
            if callable(raw):
                raw = raw()
        except Exception:
            raw = None
        if not isinstance(raw, str):
            return
        text = raw.strip()
        if not text:
            return
        try:
            result = self.app.copy_to_clipboard(text)
        except Exception:
            self.app.notify("clipboard failed", severity="error", timeout=1.5)
            return
        if asyncio.iscoroutine(result):
            try:
                asyncio.get_running_loop().create_task(result)
            except RuntimeError:
                result.close()
        self.app.notify("✓ selection copied", timeout=1.2)


# ══════════════════════════════════════════════════════════════════════
# Chrome: top navbar + composer
# ══════════════════════════════════════════════════════════════════════


class TopBar(Horizontal):
    """The navbar — brand · folder · model · Σ tokens (red) · state · sound."""

    def __init__(self, model: str) -> None:
        super().__init__(id="top-bar")
        self.model_name = short_model(model)
        self.cwd_path = Path.cwd()
        self.folder_name = self.cwd_path.name or "/"
        self._hud_state = "ready"
        self._activity: str | None = None
        self._frame = 0
        self._done_duration: float | None = None
        self._turn_started: float | None = None
        self._last_playing: bool | None = None
        self._spin_timer: Timer | None = None
        self._revert_timer: Timer | None = None
        self._sound_sync: Timer | None = None
        self._left: Static | None = None
        self._tokens_chip: Static | None = None
        self._state_chip: Static | None = None
        self._sound_chip: Static | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="top-left")
        yield Static("", id="chip-tokens")
        yield Static("", id="chip-state")
        yield Static("", id="chip-sound")

    def _brand_text(self) -> Text:
        return Text.from_markup(
            f"[{THEME['accent']}]✻[/] [#e2e6f2]jimmy[/] "
            f"[#2a3148]·[/] [#7b8296]📂 {escape(self.folder_name)}[/] "
            f"[#2a3148]·[/] [#6e7690]{escape(self.model_name)}[/]"
        )

    def on_mount(self) -> None:
        self._left = self.query_one("#top-left", Static)
        self._tokens_chip = self.query_one("#chip-tokens", Static)
        self._state_chip = self.query_one("#chip-state", Static)
        self._sound_chip = self.query_one("#chip-sound", Static)
        if self._left is not None:
            self._left.update(self._brand_text())
            self._left.tooltip = f"{self.cwd_path} · click for home (ctrl+h)"
        if self._tokens_chip is not None:
            self._tokens_chip.tooltip = "session tokens (input + output)"
        if self._state_chip is not None:
            self._state_chip.tooltip = "click to interrupt while working · press esc"
        if self._sound_chip is not None:
            self._sound_chip.tooltip = "sound — click or press ctrl+s"
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

    def on_click(self, event: events.Click) -> None:
        cid = event.control.id
        if cid == "chip-sound":
            self.app.action_toggle_sound()
        elif cid == "top-left":
            self.app.action_home()
        elif cid == "chip-state" and self._hud_state == "working":
            self.app.action_interrupt()

    def set_thinking(self) -> None:
        self._cancel_revert()
        self._turn_started = time.monotonic()
        self._set_state("working")

    def set_activity(self, label: str | None) -> None:
        self._activity = label
        if self._hud_state == "working":
            self._render_chips()

    def set_ready(self) -> None:
        self._cancel_revert()
        self._activity = None
        self._set_state("ready")

    def set_done(self, duration: float | None = None) -> None:
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
        self._render_chips()

    def refresh_tokens(self) -> None:
        self._render_chips()

    def refresh_theme(self) -> None:
        if self._left is not None:
            try:
                self._left.update(self._brand_text())
            except errors.NoWidget:
                pass
        self._render_chips()

    def _cancel_revert(self) -> None:
        if self._revert_timer is not None:
            self._revert_timer.stop()
            self._revert_timer = None

    def _sync_sound_chip(self) -> None:
        playing = self.app.sound.is_playing
        if playing != self._last_playing:
            self._render_chips()

    def _set_state(self, state: str) -> None:
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
        if self._state_chip is None or self._sound_chip is None:
            return
        try:
            self._paint_chips()
        except errors.NoWidget:
            pass

    def _paint_chips(self) -> None:
        self._last_playing = self.app.sound.is_playing

        tokens = self._tokens_chip
        if tokens is not None:
            total_in = getattr(self.app, "_total_in", 0)
            total_out = getattr(self.app, "_total_out", 0)
            tokens.tooltip = f"{total_in:,} in · {total_out:,} out — this session"
            tokens.update(
                Text.from_markup(f"[#fb7185]Σ[/] [#fb7185]{compact_count(total_in + total_out)}[/]")
            )

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

        sound = self._sound_chip
        assert sound is not None
        sound.update(sound_chip_text(self._last_playing))


class PromptInput(Input):
    """The composer input — multi-line paste flattening + size notices."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sanitizing = False
        self._prev_len = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._sanitizing:
            return
        value = event.value

        if len(value) > MAX_PASTE_CHARS:
            self._sanitizing = True
            try:
                self.value = value[:MAX_PASTE_CHARS]
                self.cursor_position = len(self.value)
            finally:
                self._sanitizing = False
            self.app.notify(
                f"input capped at {MAX_PASTE_CHARS:,} characters",
                severity="warning",
                timeout=2.0,
            )
            self._prev_len = MAX_PASTE_CHARS
            return

        if "\n" in value or "\r" in value:
            flattened = " ".join(value.split())
            self._sanitizing = True
            try:
                self.value = flattened
                self.cursor_position = len(flattened)
            finally:
                self._sanitizing = False
            self._prev_len = len(flattened)
            self.app.notify("multi-line paste flattened to one line", timeout=1.5)
            return

        if len(value) - self._prev_len > 300:
            self.app.notify(f"pasted {len(value):,} characters", timeout=1.5)
        self._prev_len = len(value)


class Composer(Vertical):
    """Prompt + slim statusline (hints left, pwd right) + ↑/↓ history."""

    HINTS_IDLE = (
        f"{keycap('ctrl+h', '⌂ home')}   [#2a3148]·[/]   "
        f"{keycap('ctrl+p', '☰ commands')}   [#2a3148]·[/]   "
        f"{keycap('ctrl+c', '⎘ copy')}   [#2a3148]·[/]   "
        f"{keycap('ctrl+q', '⏻ quit')}"
    )
    HINTS_BUSY = (
        f"{keycap('esc', '⏹ interrupt')}   [#2a3148]·[/]   "
        f"[#fbbf24]✻[/] [#8a91a8]jimmy is working[/]"
    )

    def __init__(self) -> None:
        super().__init__(id="composer")
        self._prompt_input = PromptInput(placeholder="Give Jimmy a task…", id="prompt")
        self._hints_line = Static(Text.from_markup(self.HINTS_IDLE), id="composer-hints")
        self._pwd_line = Static("", id="composer-pwd")
        self._celebrate_timer: Timer | None = None
        self._history: list[str] = []
        self._hist_index = 0
        self._draft = ""

    def compose(self) -> ComposeResult:
        yield self._prompt_input
        with Horizontal(id="composer-statusline"):
            yield self._hints_line
            yield self._pwd_line

    def on_mount(self) -> None:
        self._pwd_line.update(Text.from_markup(f"[#3a4157]▸ {escape(pretty_pwd())}[/]"))

    def on_unmount(self) -> None:
        if self._celebrate_timer is not None:
            self._celebrate_timer.stop()
            self._celebrate_timer = None

    def on_key(self, event: events.Key) -> None:
        if event.key == "up":
            event.stop()
            event.prevent_default()
            self.history_previous()
        elif event.key == "down":
            event.stop()
            event.prevent_default()
            self.history_next()

    def remember(self, text: str) -> None:
        if not text:
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._hist_index = len(self._history)
        self._draft = ""

    def history_previous(self) -> None:
        if not self._history:
            return
        if self._hist_index == len(self._history):
            self._draft = self._prompt_input.value
        self._hist_index = max(0, self._hist_index - 1)
        self._prompt_input.value = self._history[self._hist_index]
        self._prompt_input.cursor_position = len(self._prompt_input.value)

    def history_next(self) -> None:
        if not self._history:
            return
        if self._hist_index >= len(self._history):
            return
        self._hist_index += 1
        if self._hist_index >= len(self._history):
            self._hist_index = len(self._history)
            self._prompt_input.value = self._draft
        else:
            self._prompt_input.value = self._history[self._hist_index]
        self._prompt_input.cursor_position = len(self._prompt_input.value)

    def focus_input(self) -> None:
        self._prompt_input.focus()

    def clear_input(self) -> None:
        self._prompt_input.value = ""
        self._prompt_input.cursor_position = 0

    def set_busy(self, busy: bool) -> None:
        self._prompt_input.placeholder = (
            "Jimmy is working — esc to interrupt" if busy else "Give Jimmy a task…"
        )
        if busy:
            self.add_class("busy")
        else:
            self.remove_class("busy")
        markup = self.HINTS_BUSY if busy else self.HINTS_IDLE
        self._hints_line.update(Text.from_markup(markup))

    def flash_success(self) -> None:
        self.add_class("celebrate")
        if self._celebrate_timer is not None:
            self._celebrate_timer.stop()
        self._celebrate_timer = self.set_timer(1.2, self._end_celebrate)

    def _end_celebrate(self) -> None:
        self._celebrate_timer = None
        self.remove_class("celebrate")


# ══════════════════════════════════════════════════════════════════════
# Command palette (ctrl+p) — small, floating, centered, INSTANT
# ══════════════════════════════════════════════════════════════════════


class PaletteSearch(Input):
    """The palette's search box with bulletproof key interception.

    escape / up / down are handled HERE — on the focused widget itself —
    so no binding-resolution order can ever swallow them.  esc hierarchy:
    in a submenu (shortcuts/themes) esc goes BACK to commands; in the
    commands list esc closes the palette.
    """

    def on_key(self, event: events.Key) -> None:
        screen = self.screen
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            screen.palette_escape()
        elif event.key == "up":
            event.stop()
            event.prevent_default()
            screen.palette_move(-1)
        elif event.key == "down":
            event.stop()
            event.prevent_default()
            screen.palette_move(1)


class CommandPaletteScreen(ModalScreen):
    """A small premium floating command menu — never fullscreen, never slow.

        ┌─ ✦ Commands ─────────────────────── esc ✕ ─┐
        │  🔍  Search commands…                      │
        │  Suggested                                 │
        │  › ⌨  Keyboard Shortcuts                   │
        │    🎨  Theme · violet                      │
        │    ⌂  Go home                              │
        │    ⎘  Copy last prompt + reply             │
        │    ⎘  Copy whole chat                      │
        │    ♪  Sound play / stop                    │
        │    🧹  Clear chat timeline                 │
        │    ⌫  Clear input line                     │
        │    ✕  Close menu                           │
        │  ↑↓ navigate · ↵ select · esc back/close   │
        └────────────────────────────────────────────┘

    Views: ``commands`` (root) · ``shortcuts`` (keycaps) · ``themes``
    (↑↓ applies LIVE, each dot shows that theme's own color).

    CLOSE CONTRACT (this is what fixed the dead-input bug):
      All close paths funnel to ``dismiss_palette`` → ``app.close_palette``,
      which schedules the canonical ``app.pop_screen()`` via
      ``app.call_next`` (never mutating the stack mid-dispatch) and then
      EXPLICITLY restores focus to the revealed screen's input one frame
      later.  ``Screen.dismiss()`` is deliberately NOT used — its
      suspend/teardown path can leave input routing wedged.
    """

    # Escape binding backstop (priority so it wins over app bindings
    # while the modal is open).  The search-input interception and the
    # screen on_key both funnel into palette_escape as well.
    BINDINGS = [
        Binding("escape", "palette_escape_action", "Close", priority=True),
    ]

    SHORTCUT_ROWS: tuple[tuple[str, str], ...] = (
        ("↵", "send · begin"),
        ("↑ ↓", "prompt history"),
        ("esc", "interrupt jimmy / go back in menus"),
        ("ctrl+h", "home (toggle)"),
        ("ctrl+p", "command menu (toggle)"),
        ("ctrl+c", "copy last prompt + reply"),
        ("ctrl+a", "copy whole chat"),
        ("ctrl+l", "clear the input line"),
        ("ctrl+s", "sound play / stop"),
        ("ctrl+q", "quit"),
        ("drag", "mouse-select text to copy"),
        ("/", "clear · home · sound · copy · copyall · quit"),
    )

    def __init__(self) -> None:
        super().__init__(id="palette-screen")
        self._mode = "commands"  # commands | shortcuts | themes
        self._index = 0
        self._entries: list[dict[str, Any]] = []
        self._search: PaletteSearch | None = None
        self._list: Vertical | None = None
        self._section: Static | None = None
        self._title: Static | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="palette"):
            with Horizontal(id="palette-head"):
                yield Static("", id="palette-title")
                yield Static(Text.from_markup(keycap("esc", "close")), id="palette-esc")
                yield Static("✕", id="palette-close")
            yield PaletteSearch(placeholder="🔍  Search commands…", id="palette-search")
            yield Static("Suggested", id="palette-section")
            yield Vertical(id="palette-list")
            yield Static(
                "↑↓ navigate · ↵ select · esc back/close · click outside closes", id="palette-foot"
            )

    def on_mount(self) -> None:
        self._title = self.query_one("#palette-title", Static)
        self._search = self.query_one("#palette-search", PaletteSearch)
        self._list = self.query_one("#palette-list", Vertical)
        self._section = self.query_one("#palette-section", Static)
        self._paint_title()
        self._rebuild("")

        def _open() -> None:
            self._paint_selection()  # repaint once arranged — never dark
            if self._search is not None:
                self._search.focus()

        self.call_after_refresh(_open)

    # chrome ----------------------------------------------------------------

    def _paint_title(self) -> None:
        if self._title is not None:
            self._title.update(Text.from_markup(f"[{THEME['accent']}]✦[/] [#e2e6f2]Commands[/]"))

    # row model -------------------------------------------------------------

    def _commands(self) -> list[tuple[str, str, Callable[[], None]]]:
        """ALL commands live here (the root list)."""
        app = self.app
        return [
            ("⌨", "Keyboard Shortcuts", self._show_shortcuts),
            ("🎨", f"Theme · {THEME['name']}", self._show_themes),
            ("⌂", "Go home", app.action_home),
            ("⎘", "Copy last prompt + reply", app.action_copy_last),
            ("⎘", "Copy whole chat", app.action_copy_all),
            ("♪", "Sound play / stop", app.action_toggle_sound),
            ("🧹", "Clear chat timeline", app.action_clear_chat),
            ("⌫", "Clear input line", app.action_clear_input),
            ("✕", "Close menu", self.dismiss_palette),
        ]

    def _entry_markup(self, entry: dict[str, Any], selected: bool) -> Text:
        """Build a row's Text with EXPLICIT colors on every segment."""
        kind = entry["kind"]
        accent = THEME["accent"]
        if kind == "command":
            icon, label = entry["icon"], entry["label"]
            if selected:
                return Text.from_markup(
                    f"[{accent}]›[/] [{accent}]{icon}[/]  [bold #f5f6fc]{escape(label)}[/]"
                )
            return Text.from_markup(
                f"[#3a4157]›[/] [#aab2c7]{icon}[/]  [#dbe0ee]{escape(label)}[/]"
            )
        if kind == "theme":
            name = entry["label"]
            spec = THEMES.get(name, {})
            active = name == THEME["name"]
            # Each row's dot is colored with THAT theme's accent, so the
            # user sees the palette color while browsing.
            dot_color = spec.get("accent", "#4b5163")
            suffix = "  [#34d399]active[/]" if active else ""
            if selected:
                return Text.from_markup(
                    f"[{accent}]›[/] [{dot_color}]●[/]  [bold #f5f6fc]{escape(name)}[/]{suffix}"
                )
            return Text.from_markup(
                f"[#3a4157]›[/] [{dot_color}]●[/]  [#dbe0ee]{escape(name)}[/]{suffix}"
            )
        markup = entry["markup"]
        return markup if markup is not None else Text("")

    def _add_entry(
        self,
        *,
        kind: str,
        icon: str = "",
        label: str = "",
        markup: Text | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        assert self._list is not None
        entry: dict[str, Any] = {
            "kind": kind,
            "icon": icon,
            "label": label,
            "markup": markup,
            "action": action,
            "widget": None,
        }
        widget = Static(self._entry_markup(entry, False), classes="palette-item")
        entry["widget"] = widget
        self._list.mount(widget)
        self._entries.append(entry)

    def _rebuild(self, query: str) -> None:
        assert self._list is not None
        self._list.remove_children()
        self._entries = []
        self._index = 0

        if self._mode == "shortcuts":
            if self._section is not None:
                self._section.update("Keyboard Shortcuts")
            for key, desc in self.SHORTCUT_ROWS:
                self._add_entry(
                    kind="info",
                    markup=Text.from_markup(f"{keycap(key, '')}  [#aab2c7]{escape(desc)}[/]"),
                )
            # Clear exits: esc → back to commands, ✕ → close the menu.
            self._add_entry(
                kind="info",
                markup=Text.from_markup(f"{keycap('esc', '')}  [#aab2c7]back to commands[/]"),
                action=self._show_commands,
            )
            self._add_entry(
                kind="info",
                markup=Text.from_markup("[#fb7185]✕[/]  [#dbe0ee]close the menu[/]"),
                action=self.dismiss_palette,
            )
            self._paint_selection()
            return

        if self._mode == "themes":
            if self._section is not None:
                self._section.update("Theme — ↑↓ applies live")
            for name in THEME_ORDER:
                self._add_entry(
                    kind="theme", label=name, action=lambda n=name: self._apply_theme(n)
                )
            self._add_entry(
                kind="info",
                markup=Text.from_markup(f"{keycap('esc', '')}  [#aab2c7]back to commands[/]"),
                action=self._show_commands,
            )
            self._paint_selection()
            return

        if self._section is not None:
            self._section.update("Suggested")
        query = query.strip().lower()
        matched = [
            (icon, label, action)
            for icon, label, action in self._commands()
            if not query or query in label.lower() or query in icon
        ]
        if not matched:
            self._add_entry(
                kind="info", markup=Text.from_markup("[#8a91a8]no matching commands[/]")
            )
            self._paint_selection()
            return
        for icon, label, action in matched:
            self._add_entry(kind="command", icon=icon, label=label, action=action)
        self._paint_selection()

    def _paint_selection(self) -> None:
        """Repaint every row from OUR row model — no widget internals."""
        if not self.is_mounted:
            return
        for i, entry in enumerate(self._entries):
            widget: Static = entry["widget"]
            selected = i == self._index and entry["action"] is not None
            if selected:
                widget.add_class("selected")
            else:
                widget.remove_class("selected")
            widget.update(self._entry_markup(entry, selected))

    # navigation (unique names — Screen has selection APIs like
    # clear_selection that must never be shadowed) --------------------------

    def palette_move(self, delta: int) -> None:
        """Move selection; in the THEME view this APPLIES LIVE as you move."""
        indices = [i for i, e in enumerate(self._entries) if e["action"] is not None]
        if not indices:
            return
        if self._index not in indices:
            self._index = indices[0]
            self._paint_selection()
            return
        current = indices.index(self._index)
        self._index = indices[(current + delta) % len(indices)]

        # Live theme preview: landing on a theme row applies it instantly
        # (per request — no extra click needed).
        if self._mode == "themes":
            entry = self._entries[self._index]
            if entry["kind"] == "theme":
                self.app.set_theme(entry["label"])

        self._paint_selection()

    def palette_escape(self) -> None:
        """esc: submenu → back to commands · commands → close."""
        if self._mode != "commands":
            self._show_commands()
            return
        self.dismiss_palette()

    def action_palette_escape_action(self) -> None:
        self.palette_escape()

    # input / events ---------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "palette-search" and self._mode == "commands":
            self._rebuild(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "palette-search":
            return
        event.stop()
        self._run_index()

    def on_key(self, event: events.Key) -> None:
        # Backup path for when the search box ISN'T focused.
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.palette_escape()
        elif event.key == "up":
            event.stop()
            event.prevent_default()
            self.palette_move(-1)
        elif event.key == "down":
            event.stop()
            event.prevent_default()
            self.palette_move(1)

    def on_click(self, event: events.Click) -> None:
        control = event.control
        # 1) the ✕ button in the header
        if getattr(control, "id", None) == "palette-close":
            event.stop()
            self.dismiss_palette()
            return
        # 2) a row → activate it
        for index, entry in enumerate(self._entries):
            if control is entry["widget"]:
                event.stop()
                if entry["action"] is not None:
                    self._index = index
                    self._paint_selection()
                    self._run_index()
                return
        # 3) click OUTSIDE the card (the dim scrim) → close.  Walk the
        #    ancestor chain: if we never reach #palette, it was the scrim.
        node: Widget | None = control
        inside = False
        while node is not None:
            if getattr(node, "id", None) == "palette":
                inside = True
                break
            node = node.parent
        if not inside:
            self.dismiss_palette()

    def _run_index(self) -> None:
        if 0 <= self._index < len(self._entries):
            action = self._entries[self._index]["action"]
            if action is not None:
                action()

    # command actions -------------------------------------------------------

    def _show_shortcuts(self) -> None:
        self._mode = "shortcuts"
        self._rebuild("")

    def _show_themes(self) -> None:
        self._mode = "themes"
        self._rebuild("")

    def _show_commands(self) -> None:
        self._mode = "commands"
        query = self._search.value if self._search is not None else ""
        self._rebuild(query)

    def _apply_theme(self, name: str) -> None:
        """↵ / click on a theme row — apply, then return to commands."""
        self.app.set_theme(name)
        self._show_commands()

    # closing -----------------------------------------------------------------

    def dismiss_palette(self) -> None:
        """The single close path.

        Delegates to the APP's ``close_palette`` — which schedules the
        canonical ``pop_screen`` via ``call_next`` (never mutating the
        screen stack mid-dispatch) and explicitly restores focus to the
        revealed screen one frame later.  No timers, no dismiss(), no
        animation races, no dead input.
        """
        self.app.close_palette()


# ══════════════════════════════════════════════════════════════════════
# Home screen
# ══════════════════════════════════════════════════════════════════════


class HomeScreen(Screen):
    """Launch hero — themed synthwave, floating on a starfield.

    PERFORMANCE: when this screen is covered (command palette open on
    top), ``_home_frame`` skips all painting — the ambient loop costs
    nothing while the palette is open.
    """

    HOME_HINTS = f"{keycap('↵', 'begin')}   [#2a3148]·[/]   {keycap('ctrl+s', 'sound')}"

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
        self._prompt: Input | None = None
        self._hints: Static | None = None
        self._top_sound: Static | None = None
        self._bottom_wave: Static | None = None

    def compose(self) -> ComposeResult:
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
                yield Input(
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
        self._prompt = self.query_one("#home-prompt", Input)
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

    def _paint_brand(self) -> None:
        if self._brand is not None:
            try:
                self._brand.update(Text.from_markup(f"[{THEME['accent']}]✻[/] [#e2e6f2]jimmy[/]"))
            except errors.NoWidget:
                pass

    def on_click(self, event: events.Click) -> None:
        if getattr(event.control, "id", None) == "home-top-sound":
            self.app.action_toggle_sound()

    # intro + ambient animation -------------------------------------------

    def _home_frame(self) -> None:
        try:
            # Covered by another screen (palette, …) → paint nothing.
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
        t = time.monotonic() - self._started
        playing = self.app.sound.is_playing

        if playing != self._last_playing:
            self._last_playing = playing
            if self._top_sound is not None:
                self._top_sound.update(sound_chip_text(playing))

        if self._sparkles is not None:
            self._sparkles.update(_sparkle_line(t, LOGO_WIDTH))
        if self._logo is not None:
            self._logo.update(_flow_logo(t))
        if self._wave is not None:
            self._wave.update(
                _wave_text(
                    t,
                    LOGO_WIDTH,
                    amplitude=1.0 if playing else 0.45,
                    dim=not playing,
                )
            )
        if self._bottom_wave is not None:
            self._bottom_wave.update(
                _wave_text(
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
                + _flow_label("C  O  D  E", t)
                + Text("  ───", style="#2a3148")
            )

        if t >= 0.40 and self._tagline is not None:
            self._tagline.remove_class("hidden-until")
            shown = min(len(TAGLINE), int((t - 0.40) / 0.013) + 1)
            if shown >= len(TAGLINE):
                self._tagline.update(_gradient_text(TAGLINE, "#a78bfa", "#22d3ee"))
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
                + _flow_label("C  O  D  E", t)
                + Text("  ───", style="#2a3148")
            )
        if self._tagline is not None:
            self._tagline.remove_class("hidden-until")
            self._tagline.update(_gradient_text(TAGLINE, "#a78bfa", "#22d3ee"))
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
                self._top_sound.update(sound_chip_text(self.app.sound.is_playing))
        except errors.NoWidget:
            pass

    def _build_status(self) -> Text:
        app = self.app
        playing = app.sound.is_playing
        if playing:
            sound_part = f"[{THEME['accent']}]♪[/] [#fda4af]🔇[/] [#8a91a8]mute[/]"
        else:
            sound_part = "[#3a4157]♪[/] [#8a91a8]sound[/]"
        meta = (
            f"[#565d73]v{_app_version()}[/]  [#2a3148]·[/]  "
            f"[#4b5163]{escape(pretty_pwd())}[/]  [#2a3148]·[/]  "
            f"[#7b8296]{escape(short_model(str(app.provider.model)))}[/]  "
            f"[#2a3148]·[/]  {sound_part}"
        )
        if getattr(app, "_busy", False):
            elapsed = format_duration(time.monotonic() - app._turn_start)
            meta += f"  [#2a3148]·[/]  [#fbbf24]✻[/] [#8a91a8]working {elapsed}[/]"
        return Text.from_markup(meta)


# ══════════════════════════════════════════════════════════════════════
# Application
# ══════════════════════════════════════════════════════════════════════


class JimmyApp(App[None]):
    """Jimmy Code — see module docstring for the full key map."""

    TITLE = "jimmy"
    CSS_PATH = "jimmy.tcss"

    COMMANDS = set()  # built-in palette disabled; ctrl+p opens ours

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+h", "home", "Home"),
        Binding("ctrl+n", "home", "", show=False),  # silent alias
        ("ctrl+s", "toggle_sound", "Sound"),
        ("ctrl+l", "clear_input", "Clear line"),
        ("ctrl+c", "copy_last", "Copy last"),
        ("ctrl+a", "copy_all", "Copy all"),
        ("escape", "interrupt", "Interrupt"),
        Binding("ctrl+p", "command_palette", "Commands", priority=True),
    ]

    def __init__(
        self,
        *,
        provider: LLMProvider,
        initial_prompt: str | None = None,
    ) -> None:
        super().__init__()

        self.provider = provider
        self.initial_prompt = initial_prompt
        self.agent = Agent(provider)

        self.sound = SoundPlayer()
        self._theme_index = 0

        # Palette close guard — makes double-pops impossible.
        self._palette_closing = False

        # Turn state (unchanged agent plumbing — same flags as before).
        self._busy = False
        self._current_reply: AssistantMessage | None = None
        self._thinking: ThinkingRow | None = None
        self._tool_rows: dict[str, LiveToolStatus] = {}

        # Per-turn aggregates + session totals for the navbar Σ chip.
        self._turn_start = 0.0
        self._turn_in = 0
        self._turn_out = 0
        self._turn_tools = 0
        self._turn_steps = 0
        self._total_in = 0
        self._total_out = 0

        # Transcript of ONLY user/assistant text — what ctrl+c copies.
        self._transcript: list[tuple[str, str]] = []

        # Retry support.
        self._last_prompt: str | None = None

    @property
    def chat(self) -> ChatLog:
        return self.query_one(ChatLog)

    @property
    def top_bar(self) -> TopBar:
        return self.query_one(TopBar)

    @property
    def composer(self) -> Composer:
        return self.query_one(Composer)

    def compose(self) -> ComposeResult:
        yield TopBar(self.provider.model)
        yield ChatLog()
        yield Composer()

    def on_mount(self) -> None:
        self.composer.focus_input()
        if self.initial_prompt:
            prompt = self.initial_prompt
            self.call_after_refresh(self.submit, prompt)
        else:
            self.push_screen(HomeScreen(animated=True))
        self.sound.play_startup()
        # FOCUS WATCHDOG — every second, if the palette is closed and no
        # widget has focus, refocus the active screen's input.  This is
        # the permanent safety net: typing can never stay dead.
        self.set_interval(1.0, self._heal_focus)

    def on_unmount(self) -> None:
        self.sound.stop()

    # focus management -------------------------------------------------------

    def _palette_open(self) -> bool:
        return isinstance(self.screen, CommandPaletteScreen)

    def _focus_top_input(self) -> None:
        """Focus the primary input of whatever screen is on top."""
        try:
            screen = self.screen
            if isinstance(screen, HomeScreen):
                # Skip while the intro is still animating (hidden input).
                if not getattr(screen, "_revealed", True):
                    return
                prompt = screen.query_one("#home-prompt", Input)
                if not prompt.has_focus:
                    prompt.focus()
            else:
                self.composer.focus_input()
        except Exception:
            pass

    def _heal_focus(self) -> None:
        """Watchdog: idle app + no focused widget → restore the input."""
        if self._palette_open():
            return
        if self.focused is not None:
            return
        self._focus_top_input()

    def close_palette(self) -> None:
        """Close the command palette — the CANONICAL, safe way.

        * guarded against double-pops (``_palette_closing``),
        * pops via ``call_next`` so the screen stack is never mutated
          in the middle of a key/click dispatch,
        * explicitly restores focus to the revealed screen one frame
          after the pop (this is what fixed 'closed but can't type').
        """
        if self._palette_closing:
            return
        if not self._palette_open():
            return
        self._palette_closing = True

        def _pop() -> None:
            try:
                if isinstance(self.screen, CommandPaletteScreen):
                    self.pop_screen()
            except Exception:
                pass
            self._palette_closing = False
            # One frame later the revealed screen is active: give it focus.
            self.call_after_refresh(self._focus_top_input)

        self.call_next(_pop)

    # input handling ---------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""

        if event.input.id == "home-prompt":
            if not value:
                return
            if isinstance(self.screen, HomeScreen):
                self.pop_screen()
            self.call_after_refresh(self.composer.focus_input)
            if value.startswith("/"):
                self._run_command(value)
            else:
                self._try_submit(value)
        elif value.startswith("/"):
            self._run_command(value)
        else:
            self._try_submit(value)

    def _try_submit(self, text: str) -> None:
        if not text:
            return
        if self._busy:
            self.chat.append(SystemNote("jimmy is still working — esc to interrupt"))
            self.chat.pin(force=True)
            return
        self.submit(text)

    def _run_command(self, raw: str) -> None:
        command, _, _argument = raw.partition(" ")
        if command == "/clear":
            self.action_clear_chat()
        elif command == "/home":
            self.action_home()
        elif command in ("/mute", "/sound"):
            self.action_toggle_sound()
        elif command == "/copy":
            self.action_copy_last()
        elif command == "/copyall":
            self.action_copy_all()
        elif command == "/help":
            self.chat.append(
                SystemNote(
                    "commands: /clear · /home · /sound · /copy · /copyall · "
                    "/quit — drag-select text to copy it · ↑ recalls prompts"
                )
            )
            self.chat.pin(force=True)
        elif command == "/quit":
            self.action_quit()
        else:
            self.chat.append(SystemNote(f"unknown command {command} — try /help"))
            self.chat.pin(force=True)

    def _home_is_open(self) -> bool:
        return any(isinstance(screen, HomeScreen) for screen in self.screen_stack)

    # turn lifecycle (agent plumbing unchanged) ───────────────────────────

    def submit(self, text: str) -> None:
        if not text or self._busy:
            return

        self._busy = True
        self._current_reply = None
        self._thinking = None
        self._tool_rows.clear()
        self._last_prompt = text

        self._turn_start = time.monotonic()
        self._turn_in = self._turn_out = self._turn_tools = self._turn_steps = 0

        self.chat.append(UserMessage(text))
        self._transcript.append(("user", text))
        self.composer.remember(text)
        self.top_bar.set_thinking()
        self.composer.set_busy(True)

        self.run_worker(
            self._run_turn(text),
            name="agent-turn",
            group="turn",
            exclusive=True,
            thread=False,
            exit_on_error=False,
        )

    def _dismiss_thinking(self) -> None:
        row, self._thinking = self._thinking, None
        if row is not None:
            row.remove()

    async def _handle_event(self, event: AgentEvent) -> None:
        data = event.data

        if event.type == "llm_start":
            self._dismiss_thinking()
            row = ThinkingRow(model=str(data["model"]), step=int(data["step"]))
            self._thinking = row
            self.chat.append(row)
            self._turn_steps += 1
            self.top_bar.set_activity(None)
            return

        if event.type == "text":
            chunk = str(data.get("text", ""))
            if not chunk:
                return
            self._dismiss_thinking()
            if self._current_reply is None:
                self._current_reply = AssistantMessage()
                self.chat.append(self._current_reply)
            self._current_reply.append(chunk)
            self.chat.pin()
            return

        if event.type == "llm_done":
            self._dismiss_thinking()
            reply = self._current_reply
            if reply is not None:
                reply.finish_markdown()
                if reply.raw_text:
                    self._transcript.append(("assistant", reply.raw_text))
                self._current_reply = None
            usage = data["usage"]
            self._turn_in += int(usage.input_tokens)
            self._turn_out += int(usage.output_tokens)
            self._total_in += int(usage.input_tokens)
            self._total_out += int(usage.output_tokens)
            self.top_bar.refresh_tokens()
            self.chat.pin(force=True)
            return

        if event.type == "tool_start":
            call_id = str(data["id"])
            tool_name = str(data["name"])
            arguments = data.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            self._dismiss_thinking()
            icon, action, detail = tool_display(tool_name, arguments)
            row = LiveToolStatus(
                call_id=call_id,
                tool_name=tool_name,
                icon=icon,
                action=action,
                detail=detail,
            )
            self._tool_rows[call_id] = row
            self.chat.append(row)
            self._turn_tools += 1
            self.top_bar.set_activity(f"{icon} {action} {detail}".strip())
            return

        if event.type == "tool_done":
            row = self._tool_rows.get(str(data["id"]))
            if row is not None:
                row.finish(float(data["latency"]))
            self.top_bar.set_activity(None)
            self.chat.pin()
            return

        if event.type == "tool_error":
            row = self._tool_rows.get(str(data["id"]))
            error = data.get("error", RuntimeError("Tool failed."))
            if row is not None:
                row.fail(error)
            self.top_bar.set_activity(None)
            self.chat.pin()
            return

        if event.type == "error":
            error = data.get("error", RuntimeError("Unknown error."))
            self.chat.append(ErrorCard(error))
            self.chat.pin(force=True)

    async def _run_turn(self, text: str) -> None:
        try:
            async for event in self.agent.stream(text):
                await self._handle_event(event)

            self.chat.append(
                TurnSummary(
                    duration=time.monotonic() - self._turn_start,
                    input_tokens=self._turn_in,
                    output_tokens=self._turn_out,
                    tools=self._turn_tools,
                    steps=self._turn_steps,
                )
            )
            self.chat.append(PairDivider())
            self.chat.pin(force=True)
            self.top_bar.set_done(time.monotonic() - self._turn_start)
            self.composer.flash_success()

        except asyncio.CancelledError:
            self._dismiss_thinking()
            if not self.chat.is_empty:
                self.chat.append(
                    SystemNote(
                        f"⏹ interrupted · {format_duration(time.monotonic() - self._turn_start)}"
                    )
                )
                self.chat.pin(force=True)
                self.top_bar.set_interrupted()
            raise

        except Exception as exc:
            self._dismiss_thinking()
            self.chat.append(ErrorCard(exc))
            self.chat.pin(force=True)
            self.top_bar.set_error()

        finally:
            self._busy = False
            self._current_reply = None
            self._thinking = None
            self._tool_rows.clear()
            self.composer.set_busy(False)
            if not self._home_is_open():
                self.composer.focus_input()

    # actions ────────────────────────────────────────────────────────────

    def action_clear_input(self) -> None:
        self.composer.clear_input()

    def action_clear_chat(self) -> None:
        if self._busy:
            self.workers.cancel_group(self, "turn")

        self._busy = False
        self._current_reply = None
        self._thinking = None
        self._tool_rows.clear()
        self._transcript.clear()
        self._total_in = 0
        self._total_out = 0
        self.top_bar.refresh_tokens()

        self.chat.clear()

        self.top_bar.set_ready()
        self.composer.set_busy(False)
        if not self._home_is_open():
            self.composer.focus_input()

    def action_interrupt(self) -> None:
        if self._busy:
            self.workers.cancel_group(self, "turn")

    def action_retry_last(self) -> bool:
        if self._busy:
            self.notify("jimmy is still working — esc first", severity="warning", timeout=1.5)
            return False
        if not self._last_prompt:
            self.notify("nothing to retry yet", timeout=1.5)
            return False
        if self._transcript and self._transcript[-1][0] == "user":
            self._transcript.pop()
        self.submit(self._last_prompt)
        return True

    def action_home(self) -> None:
        if self._home_is_open():
            self.pop_screen()
            self.call_after_refresh(self._focus_top_input)
            return
        self.push_screen(HomeScreen(animated=False))

    def _exchange_text(self, which: str = "last") -> list[tuple[str, str]]:
        if which == "all":
            return list(self._transcript)
        for i in range(len(self._transcript) - 1, -1, -1):
            if self._transcript[i][0] == "user":
                return self._transcript[i:]
        return []

    def _copy_entries(self, entries: list[tuple[str, str]], label: str) -> None:
        if not entries:
            self.notify("nothing to copy yet", timeout=1.5)
            return
        parts = [f"❯ {text}" if role == "user" else text for role, text in entries]
        try:
            result = self.copy_to_clipboard("\n\n".join(parts))
        except Exception:
            self.notify("clipboard failed", severity="error", timeout=1.5)
            return
        if asyncio.iscoroutine(result):
            try:
                asyncio.get_running_loop().create_task(result)
            except RuntimeError:
                result.close()
        self.notify(label, timeout=1.5)

    def action_copy_last(self) -> None:
        self._copy_entries(self._exchange_text("last"), "✓ exchange copied")

    def action_copy_all(self) -> None:
        self._copy_entries(self._exchange_text("all"), "✓ whole chat copied")

    def action_toggle_sound(self) -> None:
        if self.sound.is_playing:
            self.sound.stop()
            self.notify("sound off", timeout=1.2)
        else:
            self.sound.play_startup()
            self.notify("sound on", timeout=1.2)
        self.top_bar.refresh_sound()
        for screen in self.screen_stack:
            if isinstance(screen, HomeScreen):
                screen.refresh_status()
                break

    def action_command_palette(self) -> None:
        """``ctrl+p`` — toggle the floating command menu."""
        if self._palette_open():
            self.close_palette()
            return
        self.push_screen(CommandPaletteScreen())
        self._palette_closing = False  # fresh instance, closing armed off

    def set_theme(self, name: str) -> None:
        """Apply a named theme NOW — recolors everything that reads THEME."""
        if name not in THEMES:
            return
        spec = THEMES[name]
        THEME["name"] = name
        THEME["accent"] = spec["accent"]
        THEME["accent2"] = spec["accent2"]
        _rebuild_flow(spec["stops"])
        self._theme_index = THEME_ORDER.index(name)
        self.top_bar.refresh_theme()
        for screen in self.screen_stack:
            if isinstance(screen, HomeScreen):
                screen.refresh_status()
                break

    def action_cycle_theme(self) -> None:
        next_name = THEME_ORDER[(self._theme_index + 1) % len(THEME_ORDER)]
        self.set_theme(next_name)
        self.notify(f"theme · {next_name}", timeout=1.2)

    def action_quit(self) -> None:
        self.sound.stop()
        self.exit()
