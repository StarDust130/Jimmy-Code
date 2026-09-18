"""Jimmy Code — TUI entry point.  Assembles the modular components.

Layout of the TUI package:
    kit/        helpers · theme · sound · assets · error_hints
    widgets/    rows · messages · chat_log · top_bar · composer
    screens/    home · palette · models
    app.py      THIS FILE — JimmyApp: bindings, agent loop, actions.

Agent behavior (LiteLLM streaming, tools, context, tokens, events)
lives in ``jimmy.agent`` / ``jimmy.llm``.  Notable agent contract:
    * ``max_steps`` is NOT an error — the agent saves progress and
      emits a ``max_steps`` event; the TUI shows a ▶ Continue card.
    * ``llm_done`` carries ``usage_ok`` → TurnSummary can report gaps.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, ClassVar

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, Static

from jimmy.agent import Agent, AgentEvent
from jimmy.llm.catalog import is_model_not_found, mark_unavailable
from jimmy.llm.cost_tracker import CostTracker
from jimmy.llm.model_config import ModelStore  # 🤖 model config store
from jimmy.llm.provider import LLMProvider
from jimmy.llm.provider_factory import create_provider  # 🤖 provider factory

from .kit.error_hints import friendly_error  # 🫱 human-readable errors
from .kit.helpers import format_duration, jimmy, short_model, tool_display
from .kit.sound import SoundPlayer
from .kit.theme import THEME, THEME_ORDER, THEMES, rebuild_flow
from .screens.home import HomeScreen
from .screens.models import ModelScreen  # 🤖 model picker screen
from .screens.palette import CommandPaletteScreen
from .widgets.chat_log import ChatLog
from .widgets.composer import Composer, HelpDialogScreen
from .widgets.messages import (
    AssistantMessage,
    ErrorCard,
    PairDivider,
    SystemNote,
    UserMessage,
)
from .widgets.rows import LiveToolStatus, ThinkingRow, TurnSummary
from .widgets.top_bar import TopBar


class ContinueCard(Static):
    """⏸ Step limit reached — progress saved, one-click continue."""

    def __init__(self, steps: int) -> None:
        self._steps = steps
        super().__init__("", classes="continue-card")

    def on_mount(self) -> None:
        self.tooltip = "click ▶ continue to resume the task"
        self._paint()

    def _paint(self) -> None:
        self.update(
            Text.from_markup(
                f"[#fbbf24]⏸[/] [#fda4af]step limit reached "
                f"({self._steps} steps)[/][#565d73] — progress saved ·  [/]"
                f"[#34d399]▶ continue[/]"
            )
        )

    def on_click(self, event: events.Click) -> None:
        event.stop()
        jimmy(self).continue_task()


class JimmyApp(App[None]):
    """Jimmy Code — keyboard:

    enter send · esc interrupt · ctrl+n home (one-way) · ctrl+p palette ·
    ctrl+m models · ctrl+c copy last (with tool calls) · ctrl+a copy all ·
    ctrl+l clear line · ctrl+s sound · ctrl+q quit · / = slash menu
    """

    TITLE = "jimmy"
    CSS_PATH = "jimmy.tcss"

    # RUF012: mutable class attributes must be annotated ClassVar.
    COMMANDS: ClassVar[set] = set()  # built-in palette disabled; ctrl+p opens ours

    BINDINGS: ClassVar[list] = [
        ("ctrl+q", "quit", "Quit"),
        # Home — one-way: only chat → home. Never toggles back.
        Binding("ctrl+n", "home", "Home", priority=True),
        # Sound / editor
        ("ctrl+s", "toggle_sound", "Sound"),
        ("ctrl+l", "clear_input", "Clear line"),
        # Copy
        ("ctrl+c", "copy_last", "Copy last"),
        ("ctrl+a", "copy_all", "Copy all"),
        # Interrupt
        ("escape", "interrupt", "Interrupt"),
        # Command palette
        Binding("ctrl+p", "command_palette", "Commands", priority=True),
        # 🤖 Model picker — fires when no input is focused; while typing
        #    use /model (ctrl+m is Enter's byte on standard terminals).
        ("ctrl+m", "open_models", "Models"),
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

        # 🤖 Model plumbing — saved models + 💰 session cost snapshot.
        self.model_store = ModelStore()
        self._cost_usd = 0.0

        self.sound = SoundPlayer()
        self._theme_index = 0

        # Palette close guard — makes double-pops impossible.
        self._palette_closing = False

        # Turn state.
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
        self._turn_gaps = 0  # ⚠ steps whose provider sent no usage
        self._total_in = 0
        self._total_out = 0

        # 📋 Transcript of the WHOLE exchange in chronological order:
        # ("user", …) · ("tool", …) · ("assistant", …) — what ctrl+c /
        # ctrl+a copy, so tool calls are included.
        self._transcript: list[tuple[str, str]] = []

        # Retry support.
        self._last_prompt: str | None = None

        # ⚠️ One error card per turn, ever (agent emits error AND the
        #    worker's except may fire for the same failure).
        self._error_shown = False

    # accessors ──────────────────────────────────────────────────────────

    @property
    def chat(self) -> ChatLog:
        return self.query_one(ChatLog)

    @property
    def top_bar(self) -> TopBar:
        return self.query_one(TopBar)

    @property
    def composer(self) -> Composer:
        return self.query_one(Composer)

    # lifecycle ──────────────────────────────────────────────────────────

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
        # FOCUS WATCHDOG — typing never dies.
        self.set_interval(1.0, self._heal_focus)

    def on_unmount(self) -> None:
        self.sound.stop()

    # 🫱 friendly errors ─────────────────────────────────────────────────

    def _friendly_error_card(self, error: Exception) -> ErrorCard:
        """🫱 Human error card — plain words, plus a one-click
        '🤖 Change model' escape hatch when the model is the problem."""
        fe = friendly_error(error)
        card = ErrorCard(RuntimeError(f"{fe.title}\n{fe.hint}"))

        if fe.is_model:

            def _open_models() -> None:
                self.push_screen(ModelScreen())

            card.attach_action("🤖 Change model", _open_models)

        return card

    # 🤖 multi-model ─────────────────────────────────────────────────────

    def current_model_short(self) -> str:
        """🏷️ Short ACTIVE-model name (never raises).

        ⚠️ Reads agent.provider FIRST — it is the hot-swapped source of
        truth.  (self.provider is only the boot-time provider and goes
        stale after switch_model unless synced — we sync it there too,
        but the agent is authoritative.)
        """
        try:
            model = getattr(self.agent.provider, "model", None)
        except Exception:
            model = None
        if not model:
            model = getattr(self.provider, "model", None)
        return short_model(model) if model else "model"

    def switch_model(self, name: str) -> None:
        """🤖 Switch the active model — persist, hot-swap, repaint.

        Raises if the model's API key is missing/invalid, so callers
        (palette / model screen) can show the add-form instead.
        Conversation history is KEPT — the new model continues the chat.
        """
        self.model_store.set_active(name)  # 💾 persisted
        provider = create_provider(self.model_store.active())  # 🔑 validates
        self.agent.set_provider(provider)  # 🔁 history kept
        self.provider = provider  # 🔄 keep the boot-time ref in sync
        self._cost_usd = 0.0  # 💰 fresh ledger
        try:
            self.top_bar.set_model(provider.model)  # 🏷️ brand repaint
        except Exception:
            pass  # chrome repaint must never block a model switch
        self.notify(f"🤖 {short_model(provider.model)} active", timeout=2)

    def action_open_models(self) -> None:
        """🤖 Open the model picker (ctrl+m / 🤖 in palette)."""
        self.push_screen(ModelScreen())

    # ▶️ continue after step-limit ───────────────────────────────────────

    def continue_task(self) -> None:
        """▶ Continue a step-limited task — history was saved by the
        agent, so the next turn resumes without redoing work."""
        if self._busy:
            self.notify(
                "jimmy is still working — esc first",
                severity="warning",
                timeout=1.5,
            )
            return
        self.submit(
            "Continue the previous task from where it stopped. "
            "Do not redo work that is already done."
        )

    # palette + focus ────────────────────────────────────────────────────

    def _palette_open(self) -> bool:
        return isinstance(self.screen, CommandPaletteScreen)

    def _focus_top_input(self) -> None:
        try:
            screen = self.screen
            if isinstance(screen, HomeScreen):
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
        if self._palette_open() or self.focused is not None:
            return
        self._focus_top_input()

    def close_palette(self, after: Callable[[], None] | None = None) -> None:
        """Close the palette — canonical pop via call_next + focus restore.

        ``after`` runs ONLY after the palette is actually gone.
        """
        if self._palette_closing or not self._palette_open():
            return
        self._palette_closing = True

        def _pop() -> None:
            try:
                if isinstance(self.screen, CommandPaletteScreen):
                    self.pop_screen()
            except Exception:
                pass
            self._palette_closing = False
            self.call_after_refresh(self._focus_top_input)
            if after is not None:
                after()

        self.call_next(_pop)

    # input handling ─────────────────────────────────────────────────────

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
        elif command == "/theme":
            self.action_cycle_theme()
        elif command == "/model":
            self.action_open_models()
        elif command == "/help":
            self.push_screen(HelpDialogScreen())
        elif command == "/quit":
            self.action_quit()
        else:
            self.chat.append(SystemNote(f"unknown command {command} — try /help"))
            self.chat.pin(force=True)

    def _home_is_open(self) -> bool:
        return any(isinstance(screen, HomeScreen) for screen in self.screen_stack)

    # turn lifecycle ─────────────────────────────────────────────────────

    def submit(self, text: str) -> None:
        if not text or self._busy:
            return

        self._busy = True
        self._current_reply = None
        self._thinking = None
        self._tool_rows.clear()
        self._error_shown = False
        self._last_prompt = text

        self._turn_start = time.monotonic()
        self._turn_in = self._turn_out = self._turn_tools = self._turn_steps = 0
        self._turn_gaps = 0

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

        # ── Step budget exhausted → ▶ Continue (NOT an error) ────────
        if event.type == "max_steps":
            self.chat.append(ContinueCard(int(data.get("steps", 0))))
            self.chat.pin(force=True)
            return

        if event.type == "llm_start":
            self._dismiss_thinking()
            row = ThinkingRow(model=str(data["model"]))
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
            if not data.get("usage_ok", True):
                self._turn_gaps += 1  # ⚠ provider sent no usage this step
            # 💰 Σ/$ read agent.cost — Agent.stream already added this
            #    step (single tracking point; TUI never double-adds).
            self._cost_usd = getattr(getattr(self.agent, "cost", None), "cost_usd", 0.0)
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
            # 📋 record the tool call — ctrl+c / ctrl+a include it
            self._transcript.append(("tool", f"{icon} {action} {detail}".strip()))
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
                self._transcript.append(("tool", f"✕ {row.action} {row.detail} — {error}".strip()))
            self.top_bar.set_activity(None)
            self.chat.pin()
            return

        if event.type == "error":
            # ⚠️ ONE card per turn — the worker's except may fire for
            #    the same failure the agent already reported.
            error = data.get("error", RuntimeError("Unknown error."))
            if not self._error_shown:
                self._error_shown = True
                self.chat.append(self._friendly_error_card(error))
                self.chat.pin(force=True)
            return

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
                    gaps=self._turn_gaps,
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

            # ⚰️ Model no longer available / deprecated.
            if is_model_not_found(exc):
                model = self.agent.provider.model
                mark_unavailable(model, str(exc))
                self.notify(
                    f"🤖 {short_model(model)} is no longer available — "
                    "press ctrl+m to pick another",
                    timeout=4,
                    severity="warning",
                )

            if not self._error_shown:
                self._error_shown = True
                self.chat.append(self._friendly_error_card(exc))
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
        self._cost_usd = 0.0
        if hasattr(self.agent, "cost"):
            self.agent.cost = CostTracker()  # 💰 fresh ledger
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
        # 🗑️ drop this exchange (user + tools + assistant) from transcript
        while self._transcript and self._transcript[-1][0] != "user":
            self._transcript.pop()
        if self._transcript:
            self._transcript.pop()
        self.submit(self._last_prompt)
        return True

    def action_home(self) -> None:
        if self._palette_open():
            self.close_palette()
            return
        if self._home_is_open():
            return  # one-way: ctrl+n never closes home
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
        parts: list[str] = []
        for role, text in entries:
            if role == "user":
                parts.append(f"❯ {text}")
            elif role == "tool":
                parts.append(f"▸ {text}")
            else:
                parts.append(text)
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
        if self._home_is_open():
            self.notify("⏻ Ctrl+Q to quit", timeout=1.6)
            return
        self._copy_entries(self._exchange_text("last"), "📋 Copied last")

    def action_copy_all(self) -> None:
        self._copy_entries(self._exchange_text("all"), "📋 Copied all")

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
        if self._palette_open():
            self.close_palette()
            return
        self.push_screen(CommandPaletteScreen())
        self._palette_closing = False

    def set_theme(self, name: str) -> None:
        if name not in THEMES:
            return
        spec = THEMES[name]
        THEME["name"] = name
        THEME["accent"] = spec["accent"]
        THEME["accent2"] = spec["accent2"]
        rebuild_flow(spec["stops"])
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
