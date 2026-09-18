"""Timeline rows: Thinking, Tool status, Turn summary (+ animated base).

Tool timeline UX: no step counters — the tools speak for themselves.

    ⠹ th✻inking · test-flash · 0.8s          ← sparkle drift + model + time
    ⠹ 🌿 git status --porcelain ▁▂▄▂▁ 0.4s   ← pulsing text + ACTIVITY WAVE
    ✓ 🌿 git status --porcelain · 30ms · 4 lines
    ✓ 🧪 pytest -q · 1.2s · 40 lines · ⚠ issues
    ⚠ ✏️ Editing x.ts · ⏱️ FileNotFoundError

 Latency chips are SPEED-CODED: green fast · blue normal · amber slow.
 Rows carry running/ok/err classes → colored left rail in the tcss.
 Hover any row → the raw call (tool name + arguments).
"""

from __future__ import annotations

import json
import time
from typing import Any, ClassVar

from rich.markup import escape
from rich.text import Text
from textual import errors, events
from textual.timer import Timer
from textual.widgets import Static

from ..kit.helpers import (
    SPINNER_FRAMES,
    WAVE_GLYPHS,
    classify_error,
    compact_count,
    format_duration,
    jimmy,
    short_model,
)
from ..kit.theme import THEME

# 💓 pulse colors for the ACTIVE tool row's action text — alternate on
#    every spinner tick: a heartbeat that says "this is happening now".
_PULSE_A = "#d5dae8"
_PULSE_B = "#a9b3d0"

# ⏱️ speed-coded latency chips — how fast was this tool, at a glance
_FAST, _NORM, _SLOW = "#34d399", "#93c5fd", "#fbbf24"


def _latency_color(seconds: float) -> str:
    if seconds < 0.5:
        return _FAST
    if seconds < 2.0:
        return _NORM
    return _SLOW


class AnimatedRow(Static):
    """Base class for timer-animated timeline rows (crash-hardened).

    1. NAME SAFETY — no subclass may define ``_render``/``_refresh``
       (Textual internals); ``_redraw`` is DEFINED here so a missing
       override can never raise AttributeError.
    2. LATE TIMER SAFETY — ``_safe_update`` stops the animation instead
       of crashing if the widget left the layout (chat cleared mid-tick).
    3. LATE MOUNT SAFETY — ``_finished`` blocks a late on_mount from
       restarting a resolved row's animation.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._anim_timer: Timer | None = None
        self._finished = False

    def _start_anim(self, interval: float) -> None:
        if self._finished:
            return
        if self._anim_timer is None:
            self._anim_timer = self.set_interval(interval, self._anim_tick)

    def _stop_anim(self) -> None:
        if self._anim_timer is not None:
            self._anim_timer.stop()
            self._anim_timer = None

    def _anim_tick(self) -> None:
        if self._finished:
            self._stop_anim()
            return
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


class ThinkingRow(AnimatedRow):
    """`⠹ th✻inking · model · 0.8s` — quiet and alive.

    A tiny sparkle drifts through the word while the spinner runs; the
    ACTIVE model and live elapsed time answer "what / how long" without
    any step-counter clutter.
    """

    SPARK_POS: ClassVar[tuple[str, ...]] = (
        "✻ thinking",
        "t✻hinking",
        "th✻inking",
        "thi✻nking",
    )

    def __init__(self, model: str, step: int = 0, max_steps: int = 0) -> None:
        # step/max_steps accepted for compatibility — deliberately NOT
        # shown: counters are noise, the timeline tells the story.
        self.model_name = model
        self.started = time.monotonic()
        self._frame = 0
        super().__init__("", classes="thinking-row")

    def on_mount(self) -> None:
        self.call_after_refresh(self._redraw)
        self._start_anim(0.1)

    def _redraw(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        elapsed = format_duration(time.monotonic() - self.started)
        word = self.SPARK_POS[(self._frame // 3) % len(self.SPARK_POS)]
        self._safe_update(
            Text.from_markup(
                f"[{THEME['accent']}]{SPINNER_FRAMES[self._frame]}[/] "
                f"[#8a91a8]{word}[/]  "
                f"[#3d4666]{escape(short_model(self.model_name))}[/]  "
                f"[#4b5163]{elapsed}[/]"
            )
        )


class LiveToolStatus(AnimatedRow):
    """One readable tool line — the star of the timeline.

    active   ⠹ 🌿 git status --porcelain ▁▂▄▂▁ 0.4s
             ↑ spinner + pulsing text + a tiny ACTIVITY WAVE that
               ripples while the tool runs — the row is never dead.
    done     ✓ 🌿 git status --porcelain · 30ms · 4 lines
             ↑ latency is SPEED-CODED (green/blue/amber) + one
               high-signal hint distilled from the real output.
    shell    ✓ 🧪 pytest -q · 1.2s · 40 lines · ⚠ issues
    failed   ⚠ ✏️ Editing x.ts · ⏱️ FileNotFoundError

    "Git git"-style echo is suppressed at render time: when the detail
    already starts the sentence (a git command, or the action word),
    the verb is dropped — the icon + state glyph carry the meaning.
    """

    def __init__(
        self,
        *,
        call_id: str,
        tool_name: str,
        icon: str,
        action: str,
        detail: str,
        step: int = 0,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        self.call_id = call_id
        self.tool_name = tool_name
        self.icon = icon
        self.action = action
        self.detail = detail
        self.step = step  # accepted for compatibility — not displayed
        self._arguments = arguments or {}
        self.started = time.monotonic()
        self._latency: float | None = None
        self._frame = 0
        super().__init__("", classes="live-tool-status running")

    def on_mount(self) -> None:
        # 🛰️ hover = the raw call — full depth on demand, zero clutter.
        tip = f"{self.tool_name} · {self.call_id}"
        if self._arguments:
            try:
                tip += f"\n{json.dumps(self._arguments, ensure_ascii=False, indent=2)}"
            except Exception:
                pass
        try:
            self.tooltip = tip
        except Exception:
            pass
        self.call_after_refresh(self._redraw)
        self._start_anim(0.1)

    # ── rendering helpers ────────────────────────────────────────────

    def _show_action(self) -> bool:
        """False when the detail already tells the story ('Git git')."""
        detail = self.detail.strip().lower()
        action = self.action.strip().lower()
        if not detail:
            return True
        if detail.startswith("git "):
            return False
        return not (action and detail.startswith(action))

    def _body(self) -> str:
        """The readable middle: 'icon Action detail' or 'icon detail'."""
        if self._show_action():
            label = f"{self.icon} {self.action}"
            if self.detail:
                return f"{label} {self.detail}"
            return label
        return f"{self.icon} {self.detail}".rstrip()

    def _wave(self) -> str:
        """▁▂▄▂▁ — a 5-glyph ripple from WAVE_GLYPHS, shifted per tick."""
        base = len(WAVE_GLYPHS)
        return "".join(WAVE_GLYPHS[(self._frame + i) % base] for i in range(5))

    def _redraw(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        elapsed = format_duration(time.monotonic() - self.started)
        action_color = _PULSE_A if self._frame % 2 == 0 else _PULSE_B
        self._safe_update(
            Text.from_markup(
                f"[{THEME['accent']}]{SPINNER_FRAMES[self._frame]}[/] "
                f"[{action_color}]{escape(self._body())}[/]  "
                f"[#3d4666]{self._wave()}[/]  "
                f"[#4b5163]{elapsed}[/]"
            )
        )

    # ── state transitions (called by JimmyApp) ───────────────────────

    def finish(self, latency: float, output: str | None = None) -> None:
        """Done: ✓ + SPEED-CODED latency + one hint from the result.

        ``output`` is the clipped tool result the agent already has —
        we distill ONE quiet hint (line count / issue marker) instead
        of dumping it on the timeline.  Optional: callers that don't
        pass output simply get the latency-only row.
        """
        self._finished = True  # also blocks a late on_mount restart
        self._stop_anim()
        self._latency = float(latency)
        self.remove_class("running")
        self.add_class("ok")

        hint = self._summarize_output(output)
        color = _latency_color(self._latency)

        self._safe_update(
            Text.from_markup(
                f"[#34d399]✓[/] "
                f"[#7f8aa5]{escape(self._body())}[/]  "
                f"[{color}]{format_duration(self._latency)}[/]{hint}"
            )
        )

    def _summarize_output(self, output: str | None) -> str:
        """One quiet, high-signal hint about WHAT the tool produced."""
        if not output:
            return ""

        try:
            lines = output.splitlines()
            n_lines = len(lines)

            if self.tool_name in ("read_files", "read_file", "search_files"):
                return (
                    f"  [#3a4157]·[/] [#565d73]{n_lines} lines · "
                    f"{compact_count(len(output))} chars[/]"
                )

            if self.tool_name in ("shell", "run_shell"):
                bits: list[str] = [f"{n_lines} lines"]
                if "--- stderr ---" in output or "Exit code:" in output:
                    bits.append("[#fbbf24]⚠ issues[/]")
                return "  [#3a4157]·[/] " + " ".join(bits)

            return ""
        except Exception:
            return ""  # cosmetic hint — never fail the row

    def fail(self, error: BaseException) -> None:
        self._finished = True
        self._stop_anim()
        self._latency = time.monotonic() - self.started
        self.remove_class("running")
        self.add_class("err")

        lines = str(error).strip().splitlines()
        reason = lines[0].strip() if lines and lines[0].strip() else type(error).__name__
        icon = classify_error(error)[0]
        self._safe_update(
            Text.from_markup(
                f"[#fbbf24]⚠[/] "
                f"[#fda4af]{escape(self._body())}[/]  "
                f"[#fb7185]{icon} {escape(reason[:40])}[/]"
            )
        )


class TurnSummary(AnimatedRow):
    """The ONE per-turn digest — the only place token totals appear.

        ✦ 4.8s · 17.3k in · 263 out · 6 tools · 3 rounds  ⧉ copy

    The ✦ sparkles through 4 colors on completion; clicking the row
    copies that exchange (prompt + tools + reply).  ``gaps`` > 0
    renders an honest ⚠ note about steps whose provider sent no usage.
    """

    SPARK_COLORS: ClassVar[tuple[str, ...]] = (
        "#c084fc",
        "#f472b6",
        "#22d3ee",
        "#93c5fd",
    )

    def __init__(
        self,
        *,
        duration: float,
        input_tokens: int,
        output_tokens: int,
        tools: int,
        steps: int,
        gaps: int = 0,
    ) -> None:
        self._duration = duration
        self._input = input_tokens
        self._output = output_tokens
        self._tools = tools
        self._steps = steps
        self._gaps = gaps
        self._frame = 0
        super().__init__("", classes="turn-summary")

    def on_mount(self) -> None:
        self.tooltip = "click to copy this exchange (prompt + tools + reply)"
        self.call_after_refresh(self._redraw)
        self._start_anim(0.1)

    def _anim_tick(self) -> None:
        self._frame += 1
        if self._frame >= 6:
            self._stop_anim()
            self._frame = -1
            self._finished = True
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
        if self._gaps > 0:
            parts.append(f"[#fbbf24]⚠ {self._gaps}[/][#3a4157] no-usage[/]")

        divider = "  [#2a3148]·[/]  "
        self._safe_update(Text.from_markup(f"{spark}{divider.join(parts)}  [#3a4157]⧉ copy[/]"))

    def on_click(self, event: events.Click) -> None:
        event.stop()
        jimmy(self).action_copy_last()


class PairDivider(Static):
    """A thin hairline after each completed prompt+reply pair."""

    def __init__(self) -> None:
        super().__init__("", classes="pair-divider")
