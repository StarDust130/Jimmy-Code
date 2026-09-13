"""JimmyApp — root of the TUI.

Owns only the layout and the conversation loop:

    ┌─ TopBar ─────────────────────────────┐  brand + live state pill
    │  ChatLog (1fr)                       │  scrolling transcript
    └─ Composer ───────────────────────────┘  input box + hints

Every visual piece lives in components/ with its own stylesheet in
styles/ — this file just wires them together.
"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Input

from jimmy.agent import Agent
from jimmy.llm.provider import LLMProvider

from .components.chat import ChatLog
from .components.composer import Composer
from .components.messages import (
    AssistantMessage,
    ErrorMessage,
    SystemNote,
    UserMessage,
    WelcomeMessage,
)
from .components.thinking import ThinkingRow
from .components.top_bar import TopBar


class JimmyApp(App[None]):
    """Jimmy — terminal-native AI coding assistant."""

    TITLE = "Jimmy"

    # One stylesheet per component, in layout order.
    CSS_PATH = [
        "styles/app.tcss",
        "styles/top_bar.tcss",
        "styles/chat.tcss",
        "styles/messages.tcss",
        "styles/thinking.tcss",
        "styles/composer.tcss",
    ]

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+l", "clear_chat", "Clear chat"),
        ("escape", "interrupt", "Interrupt"),
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

        self._busy = False  # a turn is streaming right now?

    # ── component shortcuts ──────────────────────────────

    @property
    def chat(self) -> ChatLog:
        return self.query_one(ChatLog)

    @property
    def top_bar(self) -> TopBar:
        return self.query_one(TopBar)

    @property
    def composer(self) -> Composer:
        return self.query_one(Composer)

    # ── layout ───────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield TopBar(self.provider.model)
        yield ChatLog()
        yield Composer()

    def on_mount(self) -> None:
        self.chat.show_welcome(model=self.provider.model)
        self.composer.focus_input()

        if self.initial_prompt:
            self.call_after_refresh(lambda: self.submit(self.initial_prompt or ""))

    # ── input flow ───────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.input.value = ""
        self.submit(event.value.strip())

    def submit(self, text: str) -> None:
        """One user turn: echo → spinner → streamed reply."""
        if not text or self._busy:
            return

        self._busy = True
        self.chat.append(UserMessage(text))
        self.top_bar.set_thinking()

        # Worker keeps the UI responsive while the agent streams.
        self.run_worker(self._run_turn(text), exclusive=True, thread=False)

    async def _run_turn(self, text: str) -> None:
        """Stream one assistant reply (runs inside a worker)."""
        thinking = ThinkingRow()
        self.chat.append(thinking)

        reply: AssistantMessage | None = None

        try:
            async for chunk in self.agent.stream(text):
                if reply is None:
                    # First token — swap the spinner for the real reply.
                    await thinking.remove()
                    reply = AssistantMessage()
                    self.chat.append(reply)

                reply.append(chunk)
                self.chat.pin()

            if reply is None:
                # Model finished without producing any text.
                await thinking.remove()
                self.chat.append(SystemNote("no response"))

            self.top_bar.set_ready()

        except asyncio.CancelledError:
            # esc was pressed — keep any partial reply, drop the spinner.
            if reply is None and thinking.parent is not None:
                thinking.remove()
            self.top_bar.set_interrupted()
            raise

        except Exception as exc:  # noqa: BLE001 — show it, don't crash
            if reply is None:
                await thinking.remove()
            self.chat.append(ErrorMessage(exc))
            self.top_bar.set_error()

        finally:
            self._busy = False
            self.composer.focus_input()

    # ── key bindings ─────────────────────────────────────

    def action_clear_chat(self) -> None:
        """Ctrl+L — wipe the transcript."""
        if self._busy:
            self.workers.cancel_group(self)
            self._busy = False

        self.chat.clear()
        self.chat.append(SystemNote("chat cleared"))
        self.top_bar.set_ready()
        self.composer.focus_input()

    def action_interrupt(self) -> None:
        """Esc — stop the in-flight request."""
        if self._busy:
            self.workers.cancel_group(self)