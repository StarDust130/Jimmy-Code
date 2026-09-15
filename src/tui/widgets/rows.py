"""Timeline rows: Thinking, Tool status, Turn summary (+ animated base)."""

from __future__ import annotations

import time
from typing import Any, ClassVar

from rich.text import Text
from textual import errors
from textual.timer import Timer
from textual.widgets import Static

from ..kit.helpers import SPINNER_FRAMES, classify_error, compact_count, format_duration, jimmy
from ..kit.theme import THEME


class AnimatedRow(Static):
    """Base class for timer-animated timeline rows (crash-hardened).

    1. NAME SAFETY — no subclass may define ``_render``/``_refresh``
       (Textual internals); ``_redraw`` is DEFINED here so a missing
       override can never raise AttributeError.
    2. LATE TIMER SAFETY — ``_safe_update`` stops the animation instead
       of crashing if the widget left the layout (chat cleared mid-tick).
    """

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


class ThinkingRow(AnimatedRow):
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


class LiveToolStatus(AnimatedRow):
    """One emoji-tagged tool line on the timeline.

    active   ⠹ 📖 Reading README.md · 0.4s
    done     ✓ 📖 Reading README.md · 84ms
    failed   ✕ ✏️ Editing auth.ts · ⏱️ timeout
    """

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
        from rich.markup import escape

        return escape(f"{self.icon} {self.action}")

    def _detail_part(self) -> str:
        from rich.markup import escape

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
        from rich.markup import escape

        self._safe_update(
            Text.from_markup(
                f"[#fb7185]✕[/] [#fda4af]{self._label()}[/]{self._detail_part()}  "
                f"[#fb7185]{icon} {escape(reason[:40])}[/]"
            )
        )


class TurnSummary(AnimatedRow):
    """The ONE per-turn digest — the only place token totals appear.

        ✦ 1.3s · 667 in · 12 out · 2 tools · 3 rounds  ⧉

    Clicking the row copies exactly that exchange (prompt + reply).
    """

    SPARK_COLORS: ClassVar[tuple[str, ...]] = ("#c084fc", "#f472b6", "#22d3ee", "#93c5fd")

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
        self._safe_update(Text.from_markup(f"{spark}{divider.join(parts)}  [#3a4157]⧉ copy[/]"))

    def on_click(self, event: Any) -> None:
        from textual import events

        if isinstance(event, events.Click):
            event.stop()
        jimmy(self).action_copy_last()
