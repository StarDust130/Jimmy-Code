"""Jimmy TUI application."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from jimmy.agent import Agent, AgentEvent
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


def format_duration(
    seconds: float,
) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"

    if seconds < 60:
        return f"{seconds:.1f}s"

    minutes = int(seconds // 60)
    remaining = int(seconds % 60)

    return f"{minutes}m {remaining:02d}s"


def tool_display(
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[str, str, str]:

    mapping = {
        "read_file": ("🔍", "Reading"),
        "read_files": ("🔍", "Reading"),
        "write_file": ("📝", "Writing"),
        "write_files": ("📝", "Writing"),
        "edit_file": ("✏️", "Editing"),
        "edit_files": ("✏️", "Editing"),
        "search_files": ("🔎", "Searching"),
        "search_file": ("🔎", "Searching"),
        "list_files": ("📂", "Listing"),
        "shell": ("▶", "Running"),
        "run_shell": ("▶", "Running"),
        "git_status": ("🌿", "Checking git"),
        "git_diff": ("🧾", "Checking diff"),
        "git_commit": ("📦", "Committing"),
    }

    icon, action = mapping.get(
        tool_name,
        ("🛠️", "Using"),
    )

    detail = ""

    for key in (
        "path",
        "file_path",
        "filepath",
        "filename",
        "command",
        "query",
        "pattern",
        "message",
    ):
        value = arguments.get(key)

        if value is not None:
            detail = str(value).strip()

            if detail:
                break

    return icon, action, detail


class LiveModelStatus(Static):
    """Live model request status."""

    def __init__(
        self,
        model: str,
        step: int,
    ) -> None:
        self.model_name = model
        self.step_number = step
        self.started = time.monotonic()
        self._timer = None

        super().__init__(
            "",
            classes="live-model-status",
        )

    def on_mount(self) -> None:
        self._timer = self.set_interval(
            0.1,
            self._refresh,
        )
        self._refresh()

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    def _refresh(self) -> None:
        elapsed = time.monotonic() - self.started

        self.update(
            Text.from_markup(
                f"[#a78bfa]✦[/] "
                f"[bold #ddd6fe]"
                f"{escape(self.model_name)}"
                f"[/]  "
                f"[#fbbf24]thinking[/]  "
                f"[#8d95a4]"
                f"{format_duration(elapsed)}"
                f"[/]  "
                f"[#6b7280]"
                f"step {self.step_number}"
                f"[/]"
            )
        )

    def finish(
        self,
        latency: float,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
    ) -> None:

        if self._timer is not None:
            self._timer.stop()

        if total_tokens > 0:
            token_text = f"{input_tokens:,} in · {output_tokens:,} out · {total_tokens:,} total"
        else:
            token_text = "usage not returned"

        self.update(
            Text.from_markup(
                f"[#6ee7b7]✓[/] "
                f"[bold #ddd6fe]"
                f"{escape(self.model_name)}"
                f"[/]  "
                f"[#8d95a4]"
                f"{format_duration(latency)}"
                f"[/]  ·  "
                f"[#60a5fa]"
                f"{token_text}"
                f"[/]"
            )
        )


class LiveToolStatus(Static):
    """Live tool status."""

    def __init__(
        self,
        *,
        call_id: str,
        tool_name: str,
        action: str,
        detail: str,
    ) -> None:
        self.call_id = call_id
        self.tool_name = tool_name
        self.action = action
        self.detail = detail

        self.started = time.monotonic()
        self._timer = None

        super().__init__(
            "",
            classes="live-tool-status",
        )

    def on_mount(self) -> None:
        self._timer = self.set_interval(
            0.1,
            self._refresh,
        )
        self._refresh()

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    def _refresh(self) -> None:
        elapsed = time.monotonic() - self.started

        detail = ""

        if self.detail:
            detail = f"  [#9ca3af]{escape(self.detail)}[/]"

        self.update(
            Text.from_markup(
                f"[#c084fc]◌[/] "
                f"[bold #e5e7eb]"
                f"{escape(self.action)}"
                f"[/]"
                f"{detail}  "
                f"[#7c8493]"
                f"{format_duration(elapsed)}"
                f"[/]"
            )
        )

    def finish(
        self,
        latency: float,
    ) -> None:
        if self._timer is not None:
            self._timer.stop()

        detail = ""

        if self.detail:
            detail = f"  [#9ca3af]{escape(self.detail)}[/]"

        self.update(
            Text.from_markup(
                f"[#6ee7b7]✓[/] "
                f"[bold #dfe3eb]"
                f"{escape(self.action)}"
                f"[/]"
                f"{detail}  "
                f"[#6ee7b7]"
                f"{format_duration(latency)}"
                f"[/]"
            )
        )

    def fail(
        self,
        error: BaseException,
    ) -> None:
        if self._timer is not None:
            self._timer.stop()

        detail = ""

        if self.detail:
            detail = f"  [#9ca3af]{escape(self.detail)}[/]"

        # Keep tool errors compact.
        error_type = type(error).__name__

        self.update(
            Text.from_markup(
                f"[#fb7185]✕[/] "
                f"[bold #fda4af]"
                f"{escape(self.action)} failed"
                f"[/]"
                f"{detail}  "
                f"[#fb7185]"
                f"{escape(error_type)}"
                f"[/]"
            )
        )


class JimmyApp(App[None]):
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

        self._current_reply: AssistantMessage | None = None

        self._model_status: LiveModelStatus | None = None

        self._tool_rows: dict[
            str,
            LiveToolStatus,
        ] = {}

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
            self.call_after_refresh(lambda: self.submit(self.initial_prompt or ""))

    def on_input_submitted(
        self,
        event: Input.Submitted,
    ) -> None:
        event.input.value = ""
        self.submit(event.value.strip())

    def submit(
        self,
        text: str,
    ) -> None:
        if not text or self._busy:
            return

        self._busy = True

        self._current_reply = None
        self._model_status = None
        self._tool_rows.clear()

        self.chat.append(UserMessage(text))

        self.top_bar.set_thinking()

        self.run_worker(
            self._run_turn(text),
            name="agent-turn",
            group="turn",
            exclusive=True,
            thread=False,
            exit_on_error=False,
        )

    async def _handle_event(
        self,
        event: AgentEvent,
    ) -> None:
        data = event.data

        # ─────────────────────────────
        # Model started
        # ─────────────────────────────

        if event.type == "llm_start":
            status = LiveModelStatus(
                model=str(data["model"]),
                step=int(data["step"]),
            )

            self._model_status = status

            self.chat.append(status)
            self.chat.pin()

            self._current_reply = None
            return

        # ─────────────────────────────
        # Streaming text
        # ─────────────────────────────

        if event.type == "text":
            text = str(data.get("text", ""))

            if not text:
                return

            if self._current_reply is None:
                self._current_reply = AssistantMessage()

                self.chat.append(self._current_reply)

            self._current_reply.append(text)
            self.chat.pin()
            return

        # ─────────────────────────────
        # Model finished
        # ─────────────────────────────

        if event.type == "llm_done":
            if self._current_reply is not None:
                self._current_reply.finish_markdown()

            status = self._model_status

            if status is not None:
                usage = data["usage"]

                status.finish(
                    latency=float(data["latency"]),
                    input_tokens=int(usage.input_tokens),
                    output_tokens=int(usage.output_tokens),
                    total_tokens=int(usage.total_tokens),
                )

            self.chat.pin()
            return

        # ─────────────────────────────
        # Tool started
        # ─────────────────────────────

        if event.type == "tool_start":
            call_id = str(data["id"])

            tool_name = str(data["name"])

            arguments = data.get(
                "arguments",
                {},
            )

            if not isinstance(
                arguments,
                dict,
            ):
                arguments = {}

            _, action, detail = tool_display(
                tool_name,
                arguments,
            )

            row = LiveToolStatus(
                call_id=call_id,
                tool_name=tool_name,
                action=action,
                detail=detail,
            )

            self._tool_rows[call_id] = row

            self.chat.append(row)
            self.chat.pin()
            return

        # ─────────────────────────────
        # Tool finished
        # ─────────────────────────────

        if event.type == "tool_done":
            call_id = str(data["id"])

            row = self._tool_rows.get(call_id)

            if row is not None:
                row.finish(float(data["latency"]))

            self.chat.pin()
            return

        # ─────────────────────────────
        # Tool failed
        # ─────────────────────────────

        if event.type == "tool_error":
            call_id = str(data["id"])

            row = self._tool_rows.get(call_id)

            error = data.get(
                "error",
                RuntimeError("Tool failed."),
            )

            if row is not None:
                row.fail(error)

            self.chat.pin()
            return

        # ─────────────────────────────
        # Fatal error
        # ─────────────────────────────

        if event.type == "error":
            error = data.get(
                "error",
                RuntimeError("Unknown error."),
            )

            self.chat.append(ErrorMessage(error))

            self.chat.pin()

    async def _run_turn(
        self,
        text: str,
    ) -> None:
        try:
            async for event in self.agent.stream(text):
                await self._handle_event(event)

            self.top_bar.set_ready()

        except asyncio.CancelledError:
            self.top_bar.set_interrupted()
            raise

        except Exception as exc:
            self.chat.append(ErrorMessage(exc))

            self.top_bar.set_error()

        finally:
            self._busy = False

            self._current_reply = None
            self._model_status = None
            self._tool_rows.clear()

            self.composer.focus_input()

    def action_clear_chat(self) -> None:
        if self._busy:
            self.workers.cancel_group(
                self,
                "turn",
            )

        self._busy = False

        self._current_reply = None
        self._model_status = None
        self._tool_rows.clear()

        self.chat.clear()

        self.chat.append(SystemNote("chat cleared"))

        self.top_bar.set_ready()
        self.composer.focus_input()

    def action_interrupt(self) -> None:
        if self._busy:
            self.workers.cancel_group(
                self,
                "turn",
            )
