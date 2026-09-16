"""Jimmy Code — TUI entry point.  Assembles the modular components.

Layout of the TUI package:
    kit/        helpers · theme · sound · assets   (pure building blocks)
    widgets/    rows · messages · chat_log · top_bar · composer
    screens/    home · palette
    app.py      THIS FILE — JimmyApp: bindings, agent loop, actions.

All agent behavior (LiteLLM streaming, tools, context, tokens, events)
is untouched and lives in ``jimmy.agent`` / ``jimmy.llm``.
"""

from __future__ import annotations

import asyncio
import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input

from jimmy.agent import Agent, AgentEvent
from jimmy.llm.provider import LLMProvider

from .kit.helpers import format_duration, tool_display
from .kit.sound import SoundPlayer
from .kit.theme import THEME, THEME_ORDER, THEMES, rebuild_flow
from .screens.home import HomeScreen
from .screens.palette import CommandPaletteScreen
from .widgets.chat_log import ChatLog
from .widgets.composer import Composer
from .widgets.messages import AssistantMessage, ErrorCard, PairDivider, SystemNote, UserMessage
from .widgets.rows import LiveToolStatus, ThinkingRow, TurnSummary
from .widgets.top_bar import TopBar


class JimmyApp(App[None]):
    """Jimmy Code — keyboard:

    enter send · esc interrupt · ctrl+n home (ctrl+n on terminals
    that support it) · ctrl+p palette · ctrl+c copy last ·
    ctrl+a copy all · ctrl+l clear line · ctrl+s sound · ctrl+q quit
    """

    TITLE = "jimmy"
    CSS_PATH = "jimmy.tcss"

    COMMANDS = set()  # built-in palette disabled; ctrl+p opens ours

    BINDINGS = [
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
        Binding(
            "ctrl+p",
            "command_palette",
            "Commands",
            priority=True,
        ),
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
        # FOCUS WATCHDOG — if the palette is closed and no widget has
        # focus, refocus the active screen's input.  Typing never dies.
        self.set_interval(1.0, self._heal_focus)

    def on_unmount(self) -> None:
        self.sound.stop()

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

    def close_palette(self) -> None:
        """Close the palette — canonical pop via call_next + focus restore."""
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

    # turn lifecycle (agent plumbing unchanged) ──────────────────────────

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
            return  # one-way: ctrl+n never closes home (esc or ↵ does)
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
        self._copy_entries(
            self._exchange_text("last"),
            "📋 Copied last",
        )

    def action_copy_all(self) -> None:
        self._copy_entries(
            self._exchange_text("all"),
            "📋 Copied all",
        )

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
