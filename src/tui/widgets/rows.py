"""Timeline rows: Thinking, Tool status, Turn summary (+ animated base).

Tool timeline UX — the row tells the STORY, not the raw command:

    ⠹ committing “looping through updates”···  0.4s   ← bright: happening NOW
    ✓  committing “looping through updates”   90ms   ← dim: done, recedes
    ✓  staging 4 files                        19ms
    ✓  reading jimmy.tcss · 128 lines         11ms
    ⚠  editing x.ts  ⏱ FileNotFoundError             ← loud: needs you

Only the ACTIVE row is bright; finished rows dim so a 9-tool turn reads
as a quiet trail, not a wall of sameness.  Latency is speed-coded
(green fast · blue normal · amber slow) but kept dim on done rows.
Hover any row → the raw call (tool name + pretty arguments).
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
    classify_error,
    clip,
    compact_count,
    format_duration,
    jimmy,
    short_model,
)
from ..kit.theme import THEME

# ⏱️ speed-coded latency colors (used on done rows, kept dim)
_FAST, _NORM, _SLOW = "#34d399", "#93c5fd", "#fbbf24"


def _latency_color(seconds: float) -> str:
    if seconds < 0.5:
        return _FAST
    if seconds < 2.0:
        return _NORM
    return _SLOW


def _basename(path: str) -> str:
    return str(path).strip().rstrip("/").split("/")[-1]


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
    """One tool call — a sentence, not a log line.

    The STORY is derived from the tool + its arguments:

        git add  + paths        →  staging 4 files
        git commit -m "…"       →  committing “fun emoji message”
        git push origin main    →  pushing origin main
        git status              →  checking git status
        pytest                  →  running tests
        read_files  [a, b, c]   →  reading a.py, b.py
        search_files "jwt"      →  searching “jwt”
        write_file  path        →  writing composer.py
        edit_files  path        →  editing composer.py
        apply_patch path        →  patching composer.py

    Without arguments the row falls back to the (icon, action, detail)
    it was given — deduped, so "Git git" echo never renders.
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
        self._arguments = arguments if isinstance(arguments, dict) else {}
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

    # ── the story engine ─────────────────────────────────────────────

    def _first(self, *keys: str) -> str:
        for key in keys:
            value = self._arguments.get(key)
            if value:
                return str(value)
        return ""

    def _story(self) -> str:
        """A human sentence for what this tool is doing — varied per
        action so a 9-tool turn never reads as nine identical rows."""
        args = self._arguments
        name = (self.tool_name or "").strip().lower()

        def q(text: str) -> str:
            text = clip(str(text).strip(), 44)
            return f"“{text}”" if text else ""

        # ── shell + git: parse the command into an English verb ─────
        if name in ("shell", "run_shell", "git", "git_tool"):
            raw = self._first("command", "cmd", "subcommand", "operation")
            parts = raw.split()
            if parts and parts[0].lower() == "git":
                parts = parts[1:]
            extra = args.get("args")
            if not parts and isinstance(extra, (list, tuple)) and extra:
                parts = [str(x) for x in extra]
            sub = parts[0].lower() if parts else ""
            rest = parts[1:]

            # commit message: explicit key OR the -m flag
            message = self._first("message")
            if not message:
                for i, part in enumerate(rest):
                    if part == "-m" and i + 1 < len(rest):
                        message = rest[i + 1]
                        break

            if name in ("git", "git_tool") and not raw and not parts:
                sub = ""  # bare git tool call

            if sub == "status":
                return "checking git status"
            if sub == "log":
                return "reading git log"
            if sub in ("diff", "show"):
                return "reviewing the diff"
            if sub in ("add", "stage"):
                paths = args.get("paths") or args.get("files") or args.get("path")
                if isinstance(paths, (list, tuple)) and paths:
                    return f"staging {len(paths)} file{'s' if len(paths) != 1 else ''}"
                if paths:
                    return f"staging {_basename(str(paths))}"
                return "staging changes"
            if sub in ("restore", "rm", "mv", "stash", "checkout"):
                return "reworking the working tree"
            if sub == "commit":
                return f"committing {q(message)}" if message else "committing"
            if sub == "push":
                return "pushing " + " ".join(rest[:2]) if rest else "pushing to the remote"
            if sub in ("pull", "fetch"):
                return "syncing with the remote"
            if sub in ("branch", "tag", "remote"):
                return "managing refs"
            if sub == "init":
                return "initializing the repo"
            if sub:
                return f"git {sub}"
            # non-git shell
            if raw:
                low = raw.lower()
                if "pytest" in low.split()[:3] or low.startswith("pytest"):
                    target = self._first("test_path", "path", "pattern")
                    return f"running tests {clip(target, 28)}".rstrip()
                if low.startswith(("python", "python3", "node", "tsx")):
                    return f"executing {q(_basename(raw.split()[0]))}"
                if low.startswith(("pip", "pip3", "uv ", "uvx", "poetry")) or " install" in low:
                    return "installing dependencies"
                return f"running {clip(raw, 40)}"
            return ""

        # ── dedicated tools ──────────────────────────────────────────
        if name in ("read_files", "read_file"):
            paths = args.get("paths") or args.get("path") or args.get("file_paths")
            if isinstance(paths, (list, tuple)) and paths:
                names = [_basename(str(p)) for p in paths]
                shown = ", ".join(names[:2]) + (f" +{len(names) - 2}" if len(names) > 2 else "")
                return f"reading {shown}"
            if paths:
                return f"reading {_basename(str(paths))}"
            return ""

        if name in ("search_files", "search_file", "grep"):
            query = self._first("query", "pattern")
            return f"searching {q(query)}" if query else "searching the workspace"

        if name in ("list_files", "glob"):
            directory = self._first("directory", "dir", "path", "folder", "pattern")
            return f"scanning {directory}" if directory else "scanning the project"

        if name in ("write_file", "write_files"):
            target = self._first("path", "file_path", "filepath", "filename", "paths")
            return f"writing {_basename(target)}" if target else "writing a file"

        if name in ("edit_file", "edit_files"):
            target = self._first("path", "file_path", "filepath", "filename", "paths")
            return f"editing {_basename(target)}" if target else "editing a file"

        if name in ("apply_patch", "apply_patch_tool"):
            target = self._first("path", "file_path", "filepath", "target")
            hunks = args.get("hunks") or args.get("edits")
            base = _basename(target) if target else "patch"
            if isinstance(hunks, (list, tuple)) and hunks:
                return f"patching {base} · {len(hunks)} hunk{'s' if len(hunks) != 1 else ''}"
            return f"patching {base}" if target else "applying a patch"

        if name in ("run_tests", "run_tests_tool", "test_runner"):
            target = self._first("test_path", "path", "pattern", "node_id", "target")
            return f"running tests {clip(target, 28)}".rstrip() if target else "running tests"

        return ""  # unknown → caller falls back to action/detail

    def _fallback_body(self) -> str:
        """Old behavior, deduped: 'icon Action detail' minus echo."""
        action = (self.action or "").strip()
        detail = (self.detail or "").strip()
        if detail and (
            detail.lower().startswith("git ")
            or (action and detail.lower().startswith(action.lower()))
        ):
            return f"{self.icon} {detail}".rstrip()
        if detail:
            return f"{self.icon} {action} {detail}".rstrip()
        return f"{self.icon} {action}".rstrip()

    def _body(self) -> str:
        return self._story() or self._fallback_body()

    # ── rendering ────────────────────────────────────────────────────

    def _redraw(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER_FRAMES)
        elapsed = format_duration(time.monotonic() - self.started)
        dots = "·" * (1 + self._frame % 3)  # breathing tail on the live row
        self._safe_update(
            Text.from_markup(
                f"[{THEME['accent']}]{SPINNER_FRAMES[self._frame]}[/] "
                f"[bold #e2e6f2]{escape(self._body())}[/][#3a4157]{dots}[/]  "
                f"[#4b5163]{elapsed}[/]"
            )
        )

    # ── state transitions (called by JimmyApp) ───────────────────────

    def finish(self, latency: float, output: str | None = None) -> None:
        """Done: ✓ + the same story, DIMMED so finished rows recede and
        only the active step is bright.  Latency is speed-coded but kept
        quiet; one high-signal hint may be distilled from the output."""
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
                f"[#565d73]{escape(self._body())}[/]  "
                f"[#3d4666]{format_duration(self._latency)}[/]"
                f"{hint}"
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
                    f"  [#3a4157]·[/] [#4b5163]{n_lines} lines · "
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
