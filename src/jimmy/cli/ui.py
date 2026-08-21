from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from jimmy.agent.events import AgentEvent

console = Console()


@dataclass(frozen=True, slots=True)
class Step:
    number: int
    turn: int
    tool: str
    detail: str
    elapsed: float
    success: bool


class JimmyUI:
    """
    Professional terminal UI for Jimmy.

    AgentLoop emits events.
    JimmyUI renders those events.
    The agent itself knows nothing about Rich or terminal layout.
    """

    def __init__(
        self,
        version: str,
        workspace: Path,
        task: str,
        show_time: bool = False,
    ) -> None:
        self.version = version
        self.workspace = workspace
        self.task = task
        self.show_time = show_time

        self.started_at = time.monotonic()

        self.turn = 0
        self.status = "starting"
        self.current_tool: str | None = None

        self.steps: list[Step] = []

        self.finished = False
        self.failed = False
        self.final_elapsed = 0.0

        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # AGENT EVENTS
    # ------------------------------------------------------------------

    def handle_event(self, event: AgentEvent) -> None:
        """Receive an event from AgentLoop."""

        with self._lock:
            if event.kind == "turn_start":
                self.turn = event.turn
                self.status = "thinking"
                self.current_tool = None

            elif event.kind == "turn_end":
                self.turn = event.turn

                if event.message == "final response":
                    self.status = "finalizing"
                else:
                    self.status = "planning"

            elif event.kind == "tool_start":
                self.turn = event.turn
                self.status = "running"
                self.current_tool = event.tool_name

            elif event.kind == "tool_end":
                self.steps.append(
                    Step(
                        number=len(self.steps) + 1,
                        turn=event.turn,
                        tool=event.tool_name or "unknown",
                        detail=self._format_tool_detail(event.arguments),
                        elapsed=event.elapsed or 0.0,
                        success=event.message != "error",
                    )
                )

                self.current_tool = None

                if event.message == "error":
                    self.status = "tool failed"
                else:
                    self.status = "planning"

            elif event.kind == "complete":
                self.finished = True
                self.failed = False
                self.status = "done"
                self.current_tool = None
                self.final_elapsed = event.elapsed or (time.monotonic() - self.started_at)

            elif event.kind == "error":
                self.finished = True
                self.failed = True
                self.status = "failed"
                self.current_tool = None
                self.final_elapsed = event.elapsed or (time.monotonic() - self.started_at)

    # ------------------------------------------------------------------
    # MAIN RENDER
    # ------------------------------------------------------------------

    def render(self) -> Panel:
        """Render the complete live UI."""

        with self._lock:
            elapsed = self.final_elapsed or (time.monotonic() - self.started_at)

            turn = self.turn
            status = self.status
            current_tool = self.current_tool
            steps = tuple(self.steps[-10:])
            finished = self.finished
            failed = self.failed

        header = self._header()

        state = self._state_line(
            turn=turn,
            status=status,
            tool=current_tool,
            elapsed=elapsed,
            finished=finished,
            failed=failed,
        )

        activity = self._activity(steps)

        task = self._task_line()

        content = Group(
            header,
            Text(""),
            state,
            Text(""),
            activity,
            Text(""),
            task,
        )

        return Panel(
            content,
            border_style=("red" if failed else "green" if finished else "grey50"),
            box=__import__("rich").box.SQUARE,
            padding=(0, 1),
        )

    # ------------------------------------------------------------------
    # HEADER
    # ------------------------------------------------------------------

    def _header(self) -> Table:
        table = Table.grid(expand=True)

        table.add_column()
        table.add_column(justify="right")

        left = Text()

        left.append(
            "JIMMY",
            style="bold white",
        )

        left.append(
            f"  v{self.version}",
            style="dim",
        )

        right = Text()

        right.append(
            self._workspace_name(),
            style="cyan",
        )

        table.add_row(left, right)

        return table

    # ------------------------------------------------------------------
    # LIVE STATE
    # ------------------------------------------------------------------

    def _state_line(
        self,
        *,
        turn: int,
        status: str,
        tool: str | None,
        elapsed: float,
        finished: bool,
        failed: bool,
    ) -> Group:
        table = Table.grid()

        table.add_column(width=2)
        table.add_column()
        table.add_column(justify="right")

        if finished:
            icon = "×" if failed else "✓"

            icon_style = "bold red" if failed else "bold green"

            text = Text()

            text.append(
                icon,
                style=icon_style,
            )

            text.append(
                f"  {status}",
                style=icon_style,
            )

        else:
            spinner = Spinner(
                "dots2",
                style="cyan",
            )

            text = Text()

            text.append(
                status,
                style="bold white",
            )

            if tool:
                text.append(
                    "  ",
                    style="dim",
                )

                text.append(
                    tool,
                    style="cyan",
                )

            table.add_row(
                spinner,
                text,
                Text(
                    f"{elapsed:.1f}s",
                    style="dim",
                ),
            )

            return Group(table)

        if turn:
            text.append(
                f"  ·  turn {turn}",
                style="dim",
            )

        table.add_row(
            Text(""),
            text,
            Text(
                f"{elapsed:.1f}s",
                style="dim",
            ),
        )

        return Group(table)

    # ------------------------------------------------------------------
    # ACTIVITY
    # ------------------------------------------------------------------

    def _activity(
        self,
        steps: tuple[Step, ...],
    ) -> Table:
        table = Table.grid(
            expand=True,
            padding=(0, 1),
        )

        table.add_column(
            width=3,
            justify="right",
        )

        table.add_column(
            width=2,
        )

        table.add_column(
            width=5,
            justify="right",
        )

        table.add_column()

        table.add_column(
            width=8,
            justify="right",
        )

        if not steps:
            table.add_row(
                "",
                "",
                "",
                Text(
                    "no tool activity yet",
                    style="dim",
                ),
                "",
            )

            return table

        for step in steps:
            icon = (
                Text(
                    "✓",
                    style="green",
                )
                if step.success
                else Text(
                    "×",
                    style="red",
                )
            )

            number = Text(
                f"{step.number:02d}",
                style="dim",
            )

            turn = Text(
                f"T{step.turn}",
                style="dim",
            )

            line = Text()

            line.append(
                step.tool,
                style="bold white",
            )

            if step.detail:
                line.append(
                    "  ",
                    style="dim",
                )

                line.append(
                    step.detail,
                    style="dim",
                )

            duration = Text(
                f"{step.elapsed:.2f}s",
                style="dim",
            )

            table.add_row(
                number,
                icon,
                turn,
                line,
                duration,
            )

        return table

    # ------------------------------------------------------------------
    # TASK
    # ------------------------------------------------------------------

    def _task_line(self) -> Text:
        task = self._truncate(
            self.task.replace("\n", " "),
            110,
        )

        text = Text()

        text.append(
            "> ",
            style="bold cyan",
        )

        text.append(
            task,
            style="white",
        )

        return text

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _workspace_name(self) -> str:
        return self.workspace.name or str(self.workspace)

    @staticmethod
    def _truncate(
        value: str,
        limit: int,
    ) -> str:
        if len(value) <= limit:
            return value

        return value[: limit - 3] + "..."

    @staticmethod
    def _format_tool_detail(
        arguments: dict[str, Any] | None,
    ) -> str:
        if not arguments:
            return ""

        preferred = (
            "path",
            "file_path",
            "filename",
            "query",
            "pattern",
            "command",
        )

        for key in preferred:
            value = arguments.get(key)

            if value is None:
                continue

            return str(value).replace(
                "\n",
                " ",
            )[:80]

        return ""

    def final_message(self) -> str:
        if self.failed:
            return f"failed in {self.final_elapsed:.1f}s · {len(self.steps)} steps"

        return f"done in {self.final_elapsed:.1f}s · {len(self.steps)} steps"


# ==========================================================================
# PUBLIC UI FUNCTIONS
# ==========================================================================


def run_with_loading(
    agent,
    prompt: str,
    version: str,
    workspace: Path,
    show_time: bool = False,
) -> str:
    """
    Run the agent with the live terminal UI.

    The agent runs in a worker thread.
    Rich owns the terminal rendering.
    """

    ui = JimmyUI(
        version=version,
        workspace=workspace,
        task=prompt,
        show_time=show_time,
    )

    with ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="jimmy",
    ) as executor:
        future = executor.submit(
            agent.run,
            prompt,
            ui.handle_event,
        )

        with Live(
            ui.render(),
            console=console,
            refresh_per_second=10,
            transient=False,
        ) as live:
            while not future.done():
                live.update(
                    ui.render(),
                    refresh=True,
                )

                time.sleep(0.08)

            live.update(
                ui.render(),
                refresh=True,
            )

        try:
            result = future.result()

        except Exception as exc:
            console.print()

            console.print(
                Text(
                    f"error: {type(exc).__name__}: {exc}",
                    style="bold red",
                )
            )

            raise typer.Exit(code=1) from exc

    console.print()

    console.print(
        Text(
            ui.final_message(),
            style="dim",
        )
    )

    return result


def show_banner(
    version: str,
    workspace: Path,
) -> None:
    """
    Kept for compatibility.

    The live UI already contains the header,
    so this intentionally does nothing.
    """
    return


def show_result(result: str) -> None:
    """Render Jimmy's final response cleanly."""

    console.print()

    separator = Text(
        "─" * min(console.width, 96),
        style="grey35",
    )

    console.print(separator)

    title = Text()

    title.append(
        "Jimmy",
        style="bold white",
    )

    title.append(
        "  ",
    )

    title.append(
        "response",
        style="dim",
    )

    console.print(title)

    console.print()

    console.print(
        result.strip() or "No response.",
    )

    console.print()
