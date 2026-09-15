"""JimmyApp — root of the TUI."""

from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from jimmy.agent import Agent
from jimmy.llm.provider import LLMProvider

from .components.chat import ChatLog
from .components.composer import Composer
from .components.messages import (
    AssistantMessage,
    ErrorMessage,
    SystemNote,
    UserMessage,
)
from .components.top_bar import TopBar


class ActivityRow(Static):
    """Compact live activity/status row."""

    def __init__(self, text: str = "◌  thinking…") -> None:
        super().__init__(text, classes="activity-row")

    def set_text(self, text: str) -> None:
        self.update(text)


class JimmyApp(App[None]):
    """Jimmy — terminal-native AI coding assistant."""

    TITLE = "Jimmy"

    CSS_PATH = "jimmy.tcss"

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+l", "clear_chat", "Clear"),
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

        self._busy = False
        self._activity: ActivityRow | None = None

    # ─────────────────────────────────────────────
    # shortcuts
    # ─────────────────────────────────────────────

    @property
    def chat(self) -> ChatLog:
        return self.query_one(ChatLog)

    @property
    def top_bar(self) -> TopBar:
        return self.query_one(TopBar)

    @property
    def composer(self) -> Composer:
        return self.query_one(Composer)

    # ─────────────────────────────────────────────
    # layout
    # ─────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield TopBar(self.provider.model)
        yield ChatLog()
        yield Composer()

    def on_mount(self) -> None:
        # Don't show the large welcome block.
        self.composer.focus_input()

        if self.initial_prompt:
            self.call_after_refresh(lambda: self.submit(self.initial_prompt or ""))

    # ─────────────────────────────────────────────
    # input
    # ─────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.input.value = ""
        self.submit(event.value.strip())

    def submit(self, text: str) -> None:
        """Start one user turn."""

        if not text or self._busy:
            return

        self._busy = True

        self.chat.append(UserMessage(text))

        self.top_bar.set_thinking()

        self._activity = ActivityRow()
        self.chat.append(self._activity)

        self.run_worker(
            self._run_turn(text),
            exclusive=True,
            thread=False,
            group="turn",
        )

    # ─────────────────────────────────────────────
    # agent events
    # ─────────────────────────────────────────────

    def _agent_event(
        self,
        event: str,
        data: dict[str, Any],
    ) -> None:
        """Display compact observable agent activity."""

        if self._activity is None:
            return

        if event == "tool_start":
            name = data["name"]

            self._activity.set_text(f"◌  {name}  running…")

        elif event == "tool_done":
            name = data["name"]
            latency = data["latency"]

            self._activity.set_text(f"✓  {name}  {latency * 1000:.0f}ms")

        elif event == "llm_done":
            latency = data["latency"]
            usage = data["usage"]

            self._activity.set_text(
                f"◌  {self.provider.model}  {latency * 1000:.0f}ms · {usage.total_tokens:,} tokens"
            )

        elif event == "error":
            source = data.get("source", "unknown")
            name = data.get("name")

            if name:
                self._activity.set_text(f"✕  {source} · {name} failed")
            else:
                self._activity.set_text(f"✕  {source} failed")

    # ─────────────────────────────────────────────
    # turn
    # ─────────────────────────────────────────────

    async def _run_turn(self, text: str) -> None:
        reply: AssistantMessage | None = None

        try:
            async for chunk in self.agent.stream(
                text,
                on_event=self._agent_event,
            ):
                if reply is None:
                    if self._activity is not None:
                        self._activity.remove()
                        self._activity = None

                    reply = AssistantMessage()
                    self.chat.append(reply)

                reply.append(chunk)
                self.chat.pin()

            if reply is None:
                if self._activity is not None:
                    self._activity.remove()
                    self._activity = None

                self.chat.append(SystemNote("no response"))

            self.top_bar.set_ready()

        except asyncio.CancelledError:
            if self._activity is not None:
                self._activity.remove()
                self._activity = None

            self.top_bar.set_interrupted()
            raise

        except Exception as exc:
            if self._activity is not None:
                self._activity.remove()
                self._activity = None

            self.chat.append(ErrorMessage(exc))
            self.top_bar.set_error()

        finally:
            self._busy = False
            self.composer.focus_input()

    # ─────────────────────────────────────────────
    # actions
    # ─────────────────────────────────────────────

    def action_clear_chat(self) -> None:
        if self._busy:
            self.workers.cancel_group(self, "turn")
            self._busy = False

        self.chat.clear()
        self._activity = None

        self.chat.append(SystemNote("chat cleared"))

        self.top_bar.set_ready()
        self.composer.focus_input()

    def action_interrupt(self) -> None:
        if self._busy:
            self.workers.cancel_group(self, "turn")
