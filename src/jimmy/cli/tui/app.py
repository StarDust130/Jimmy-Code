from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Input, RichLog, Static

from jimmy.agent.events import AgentEvent

LOGO = r"""
      ██╗██╗███╗   ███╗███╗   ███╗██╗   ██╗
      ██║██║████╗ ████║████╗ ████║╚██╗ ██╔╝
      ██║██║██╔████╔██║██╔████╔██║ ╚████╔╝
 ██   ██║██║██║╚██╔╝██║██║╚██╔╝██║  ╚██╔╝
 ╚█████╔╝██║██║ ╚═╝ ██║██║ ╚═╝ ██║   ██║
  ╚════╝ ╚═╝╚═╝     ╚═╝╚═╝     ╚═╝   ╚═╝
""".strip("\n")


class JimmyTUI(App[None]):
    """Persistent terminal UI for Jimmy."""

    CSS_PATH = "styles.tcss"
    TITLE = "Jimmy"

    BINDINGS = [
        ("ctrl+c", "cancel_task", "Cancel"),
        ("q", "quit_app", "Quit"),
    ]

    status = reactive("ready")
    elapsed = reactive(0.0)
    turn = reactive(0)
    current_tool = reactive("")
    running = reactive(False)

    def __init__(
        self,
        *,
        agent: Any,
        initial_task: str | None,
        version: str,
        workspace: Path,
        show_time: bool = False,
    ) -> None:
        super().__init__()

        self._agent = agent
        self._initial_task = initial_task
        self._version = version
        self._workspace = workspace
        self._show_time = show_time

        self._task_started_at = time.monotonic()

        self._last_error: str | None = None
        self._step_number = 0

        self._worker_cancelled = False

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static(
                f"[bold]JIMMY[/bold]  v{self._version}",
                id="brand",
            ),
            Static(
                self._workspace.name or str(self._workspace),
                id="project",
            ),
            Static(
                "0.0s",
                id="clock",
            ),
            id="topbar",
        )

        yield Vertical(
            Static(
                LOGO,
                id="logo",
            ),
            Static(
                "ready",
                id="status",
            ),
            RichLog(
                id="activity",
                highlight=False,
                markup=False,
                wrap=True,
                auto_scroll=True,
            ),
            Input(
                placeholder="What should Jimmy do?",
                id="prompt",
            ),
            id="main",
        )

        yield Footer()

    def on_mount(self) -> None:
        """Initialize the persistent session."""

        self.set_interval(
            0.1,
            self._refresh_clock,
        )

        prompt = self.query_one(
            "#prompt",
            Input,
        )

        prompt.focus()

        if self._initial_task:
            self._submit_task(self._initial_task)

    # ------------------------------------------------------------------
    # INPUT
    # ------------------------------------------------------------------

    def on_input_submitted(
        self,
        event: Input.Submitted,
    ) -> None:
        """Start another Jimmy task when Enter is pressed."""

        if self.running:
            return

        task = event.value.strip()

        if not task:
            return

        event.input.value = ""

        self._submit_task(task)

    def _submit_task(
        self,
        task: str,
    ) -> None:
        """Prepare the UI for a new agent run."""

        if self.running:
            return

        self.running = True
        self.status = "thinking"
        self.turn = 0
        self.current_tool = ""
        self.elapsed = 0.0
        self._task_started_at = time.monotonic()
        self._last_error = None
        self._step_number = 0

        activity = self.query_one(
            "#activity",
            RichLog,
        )

        activity.write("")

        prompt_line = Text()

        prompt_line.append(
            "> ",
            style="cyan",
        )

        prompt_line.append(
            task,
            style="bold white",
        )

        activity.write(prompt_line)

        self._update_status()

        prompt = self.query_one(
            "#prompt",
            Input,
        )

        prompt.disabled = True

        self._start_agent(task)

    # ------------------------------------------------------------------
    # CLOCK
    # ------------------------------------------------------------------

    def _refresh_clock(self) -> None:
        """Update the live task timer."""

        if self.running:
            self.elapsed = time.monotonic() - self._task_started_at

        clock = self.query_one(
            "#clock",
            Static,
        )

        clock.update(f"{self.elapsed:.1f}s")

    # ------------------------------------------------------------------
    # AGENT WORKER
    # ------------------------------------------------------------------

    @work(
        thread=True,
        group="agent",
        exclusive=True,
        exit_on_error=False,
    )
    def _start_agent(
        self,
        task: str,
    ) -> None:
        """Run AgentLoop outside the Textual UI thread."""

        try:
            self._agent.run(
                task,
                self._agent_event,
            )

        except Exception as exc:
            self.call_from_thread(
                self._agent_failed,
                exc,
            )

    def _agent_event(
        self,
        event: AgentEvent,
    ) -> None:
        """Send agent events back to the UI thread."""

        self.call_from_thread(
            self._handle_agent_event,
            event,
        )

    # ------------------------------------------------------------------
    # AGENT EVENTS
    # ------------------------------------------------------------------

    def _handle_agent_event(
        self,
        event: AgentEvent,
    ) -> None:
        """Handle an AgentLoop event."""

        activity = self.query_one(
            "#activity",
            RichLog,
        )

        self.turn = event.turn

        if event.kind == "turn_start":
            self.status = "thinking"
            self.current_tool = ""
            self._update_status()

            activity.write(self._turn_text(event.turn))

        elif event.kind == "turn_end":
            if event.message == "final response":
                self.status = "finalizing"
            else:
                self.status = "planning"

            self._update_status()

        elif event.kind == "tool_start":
            self.status = "running"
            self.current_tool = event.tool_name or "unknown"

            self._update_status()

            activity.write(
                self._tool_start_text(
                    event.turn,
                    event.tool_name,
                    event.arguments,
                )
            )

        elif event.kind == "tool_end":
            self._step_number += 1

            success = event.message != "error"

            activity.write(
                self._tool_end_text(
                    event.elapsed or 0.0,
                    success,
                )
            )

            self.current_tool = ""

            self.status = "tool failed" if not success else "planning"

            self._update_status()

        elif event.kind == "complete":
            self._task_finished(
                event.message or "",
                event.elapsed,
            )

        elif event.kind == "error":
            self._agent_failed(RuntimeError(event.message or "Jimmy failed."))

    # ------------------------------------------------------------------
    # TASK FINISH
    # ------------------------------------------------------------------

    def _task_finished(
        self,
        result: str,
        elapsed: float | None,
    ) -> None:
        """Finish one task but keep Jimmy open."""

        self.running = False
        self.status = "ready"
        self.current_tool = ""

        self.elapsed = elapsed or (time.monotonic() - self._task_started_at)

        activity = self.query_one(
            "#activity",
            RichLog,
        )

        activity.write("")

        activity.write(
            Text(
                "✓ done",
                style="bold green",
            )
        )

        activity.write(
            Text(
                self._summary(),
                style="dim",
            )
        )

        if result.strip():
            activity.write("")
            activity.write(result.strip())

        activity.write("")

        self._enable_prompt()
        self._update_status()

    # ------------------------------------------------------------------
    # ERROR
    # ------------------------------------------------------------------

    def _agent_failed(
        self,
        exc: Exception,
    ) -> None:
        """Finish a failed task without exiting Jimmy."""

        self.running = False
        self.status = "error"
        self.current_tool = ""

        self._last_error = str(exc)

        self.elapsed = time.monotonic() - self._task_started_at

        activity = self.query_one(
            "#activity",
            RichLog,
        )

        activity.write("")

        activity.write(
            Text(
                f"× {type(exc).__name__}: {exc}",
                style="bold red",
            )
        )

        activity.write(
            Text(
                self._summary(),
                style="dim",
            )
        )

        activity.write("")

        self._enable_prompt()
        self._update_status()

    # ------------------------------------------------------------------
    # CANCEL
    # ------------------------------------------------------------------

    def action_cancel_task(self) -> None:
        """Cancel the current task."""

        if not self.running:
            return

        self._worker_cancelled = True

        self.running = False
        self.status = "ready"
        self.current_tool = ""

        activity = self.query_one(
            "#activity",
            RichLog,
        )

        activity.write("")
        activity.write(
            Text(
                "task cancelled",
                style="yellow",
            )
        )
        activity.write("")

        self._enable_prompt()
        self._update_status()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _enable_prompt(self) -> None:
        prompt = self.query_one(
            "#prompt",
            Input,
        )

        prompt.disabled = False
        prompt.focus()

    def _update_status(self) -> None:
        status = self.query_one(
            "#status",
            Static,
        )

        status.update(self._status_text())

    def _status_text(self) -> Text:
        text = Text()

        if self.running:
            text.append(
                "● ",
                style="cyan",
            )

            text.append(
                self.status,
                style="bold white",
            )

        elif self.status == "error":
            text.append(
                "× ",
                style="bold red",
            )

            text.append(
                "error",
                style="bold red",
            )

        else:
            text.append(
                "› ",
                style="green",
            )

            text.append(
                "ready",
                style="bold green",
            )

        if self.turn:
            text.append(
                f"  ·  turn {self.turn}",
                style="dim",
            )

        if self.current_tool:
            text.append(
                "  ·  ",
                style="dim",
            )

            text.append(
                self.current_tool,
                style="cyan",
            )

        return text

    # ------------------------------------------------------------------
    # RENDER HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _turn_text(turn: int) -> Text:
        text = Text()

        text.append(
            f"turn {turn}",
            style="bold white",
        )

        return text

    @classmethod
    def _tool_start_text(
        cls,
        turn: int,
        tool_name: str | None,
        arguments: dict[str, Any] | None,
    ) -> Text:
        text = Text()

        text.append(
            f"{turn:02d} ",
            style="dim",
        )

        text.append(
            "→ ",
            style="cyan",
        )

        text.append(
            tool_name or "unknown",
            style="bold white",
        )

        detail = cls._tool_detail(arguments)

        if detail:
            text.append(
                f"  {detail}",
                style="dim",
            )

        return text

    @staticmethod
    def _tool_end_text(
        elapsed: float,
        success: bool,
    ) -> Text:
        text = Text()

        text.append(
            "   ",
        )

        text.append(
            "✓ " if success else "× ",
            style=("green" if success else "red"),
        )

        text.append(
            f"{elapsed:.2f}s",
            style="dim",
        )

        return text

    @staticmethod
    def _tool_detail(
        arguments: dict[str, Any] | None,
    ) -> str:
        if not arguments:
            return ""

        for key in (
            "path",
            "file_path",
            "filename",
            "query",
            "pattern",
            "command",
        ):
            value = arguments.get(key)

            if value is not None:
                return str(value).replace(
                    "\n",
                    " ",
                )[:90]

        return ""

    def _summary(self) -> str:
        return f"{self.elapsed:.1f}s  ·  {self._step_number} tool steps  ·  turn {self.turn}"

    # ------------------------------------------------------------------
    # QUIT
    # ------------------------------------------------------------------

    def action_quit_app(self) -> None:
        """Quit the Jimmy session."""

        self.exit()


def run_tui(
    *,
    agent: Any,
    initial_task: str | None,
    version: str,
    workspace: Path,
    show_time: bool = False,
) -> None:
    """Start the persistent Jimmy TUI."""

    app = JimmyTUI(
        agent=agent,
        initial_task=initial_task,
        version=version,
        workspace=workspace,
        show_time=show_time,
    )

    app.run()

