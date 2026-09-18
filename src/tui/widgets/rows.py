"""Timeline rows: Thinking, Tool status, Turn summary (+ animated base).

Tool timeline UX (what makes a flood of calls readable):

    ⠹ Step 3/25 · 0.8s                    ← ThinkingRow (budget visible)
    ── step 3 ──────────────────────      ← StepHeader (auto, once/step)
    ⠹ [3] 📖 Reading README.md            ← active, live
    ✓ [3] 📖 Reading README.md · 84ms · 2.1k   ← done: latency + size
    ✓ [3] 🧾 12 lines · ⚠ issues · 220ms  ← shell runs summarize output
    ⚠ [3] ✏️ Editing x.ts · FileNotFoundError   ← failures keep reason
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

from rich.markup import escape
from rich.text import Text
from textual import errors, events
from textual.timer import Timer
from textual.widgets import Static

from ..kit.helpers import (
    SPINNER_FRAMES,
    classify_error,
    compact_count,
    format_duration,
    jimmy,
)
from ..kit.theme import THEME


class AnimatedRow(Static):
    """Base class for timer-animated timeline rows (crash-hardened).

    1. NAME SAFETY — no subclass may define ``_render``/``_refresh``
       (Textual internals); ``_redraw`` is DEFINED here so a missing
       override can never raise AttributeError.
    2. LATE TIMER SAFETY — ``_safe_update`` stops the animation instead
       of crashing if the widget left the layout (chat cleared mid-tick).
    3. LATE MOUNT SAFETY — ``on_mount`` can run AFTER ``finish()``/
       ``fail()`` (mounting is asynchronous).  ``_finished`` makes the
       guard bidirectional: a finished row can never start (or resume)
       its animation.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._anim_timer: Timer | None = None
        self._finished = False

    def _start_anim(self, interval: float) -> None:
        if self._finished:
            return  # row already resolved — never animate again
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
    """`⠹ Step 3/25 · 0.8s` — the model is thinking, budget visible."""

    def __init__(self, model: str, step: int, max_steps: int = 25) -> None:
        self.model_name = model
        self.step = step
        self.max_steps = max_steps
        self.started = time.monotonic()
        self._frame = 0
        super().__init__("", classes="thinking-row")

    def on_mount(self) -> None:
        self.call_after_refresh(self._redraw)
        self._start_anim(0.1)

    def _redraw(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        elapsed = format_duration(time.monotonic() - self.started)
        self._safe_update(
            Text.from_markup(
                f"[{THEME['accent']}]{SPINNER_FRAMES[self._frame]}[/] "
                f"[#8a91a8]Step {self.step}/{self.max_steps}[/]  "
                f"[#4b5163]{elapsed}[/]"
            )
        )


class StepHeader(Static):
    """`── step 3 ──────────` — one quiet divider per agent step.

    Mounted by the App the FIRST time a step emits tools; groups the
    tool calls of that step so a batch reads as one block.  Older
    headers dim via the ``old`` class (App toggles it when a later
    step starts).
    """

    def __init__(self, step: int) -> None:
        self.step = step
        super().__init__("", classes="step-header")

    def on_mount(self) -> None:
        self._paint()

    def _paint(self) -> None:
        out = Text()
        out.append(f"── step {self.step} ", style="#3a4157")
        out.append("─" * 18, style="#3a4157")
        self.update(out)

    def make_old(self) -> None:
        try:
            self.add_class("old")
        except errors.NoWidget:
            pass


class LiveToolStatus(AnimatedRow):
    """One readable tool line on the timeline.

    active   ⠹ [3] 📖 Reading README.md
    done     ✓ [3] 📖 Reading README.md · 84ms · 2.1k
    shell    ✓ [3] 🧾 12 lines · ⚠ issues · 220ms
    failed   ⚠ [3] ✏️ Editing x.ts · ⏱️ timeout
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
    ) -> None:
        self.call_id = call_id
        self.tool_name = tool_name
        self.icon = icon
        self.action = action
        self.detail = detail
        self.step = step
        self.started = time.monotonic()
        self._frame = 0
        super().__init__("", classes="live-tool-status")

    def on_mount(self) -> None:
        self.call_after_refresh(self._redraw)
        self._start_anim(0.1)

    # step tag — dim, only when we know it
    def _tag(self) -> str:
        return f"[#3a4157][{self.step}][/]" if self.step > 0 else ""

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
                f"{self._tag()} "
                f"[#d5dae8]{self._label()}[/]{self._detail_part()}  "
                f"[#4b5163]{elapsed}[/]"
            )
        )

    def finish(self, latency: float, output: str | None = None) -> None:
        """Done: ✓ + latency + a *useful* tail derived from the result.

        ``output`` is the clipped tool result the agent already has —
        we distill ONE quiet hint from it (line count / issue marker)
        instead of dumping it on the timeline.  Optional: callers that
        don't pass output simply get the latency-only row.
        """
        self._finished = True  # also blocks a late on_mount restart
        self._stop_anim()

        hint = self._summarize_output(output)

        self._safe_update(
            Text.from_markup(
                f"[#34d399]✓[/] {self._tag()} "
                f"[#7f8aa5]{self._label()}[/]{self._detail_part()}  "
                f"[#34d399]{format_duration(latency)}[/]{hint}"
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
        lines = str(error).strip().splitlines()
        reason = lines[0].strip() if lines and lines[0].strip() else type(error).__name__
        icon = classify_error(error)[0]
        self._safe_update(
            Text.from_markup(
                f"[#fbbf24]⚠[/] {self._tag()} "
                f"[#fda4af]{self._label()}[/]{self._detail_part()}  "
                f"[#fb7185]{icon} {escape(reason[:40])}[/]"
            )
        )


class TurnSummary(AnimatedRow):
    """The ONE per-turn digest — the only place token totals appear.

        ✦ 4.8s · 17.3k in · 263 out · 6 tools · 3 rounds  ⧉ copy

    The ✦ sparkles briefly on completion; clicking the row copies that
    exchange (prompt + reply).  ``gaps`` > 0 renders an honest ⚠ note
    about steps whose provider sent no usage.
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
        self.tooltip = "click to copy this exchange (prompt + reply)"
        self.call_after_refresh(self._redraw)
        self._start_anim(0.1)

    def _anim_tick(self) -> None:
        self._frame += 1
        if self._frame >= 6:
            self._stop_anim()
            self._frame = -1
            self._finished = True  # sparkle done — never restart it
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
