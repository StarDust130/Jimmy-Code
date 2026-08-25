from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, ClassVar

from rich.syntax import Syntax
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, RichLog, Static

from jimmy.agent.events import AgentEvent
from jimmy.permissions.manager import PermissionMode

LOGO = r"""
     ██╗██╗███╗   ███╗███╗   ███╗██╗   ██╗   ██████╗ ██████╗ ██████╗ ███████╗
     ██║██║████╗ ████║████╗ ████║╚██╗ ██╔╝  ██╔════╝██╔═══██╗██╔══██╗██╔════╝
     ██║██║██╔████╔██║██╔████╔██║ ╚████╔╝   ██║     ██║   ██║██║  ██║█████╗
██   ██║██║██║╚██╔╝██║██║╚██╔╝██║  ╚██╔╝    ██║     ██║   ██║██║  ██║██╔══╝
╚█████╔╝██║██║ ╚═╝ ██║██║ ╚═╝ ██║   ██║     ╚██████╗╚██████╔╝██████╔╝███████╗
 ╚════╝ ╚═╝╚═╝     ╚═╝╚═╝     ╚═╝   ╚═╝      ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝
""".strip("\n")


SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

THINKING_BAR = [
    "▰▱▱▱▱▱▱▱",
    "▰▰▱▱▱▱▱▱",
    "▰▰▰▱▱▱▱▱",
    "▰▰▰▰▱▱▱▱",
    "▰▰▰▰▰▱▱▱",
    "▰▰▰▰▰▰▱▱",
    "▰▰▰▰▰▰▰▱",
    "▰▰▰▰▰▰▰▰",
    "▱▰▰▰▰▰▰▰",
    "▱▱▰▰▰▰▰▰",
    "▱▱▱▰▰▰▰▰",
    "▱▱▱▱▰▰▰▰",
    "▱▱▱▱▱▰▰▰",
    "▱▱▱▱▱▱▰▰",
    "▱▱▱▱▱▱▱▰",
    "▱▱▱▱▱▱▱▱",
]


TOOL_ICONS: dict[str, str] = {
    "read_file": "◆",
    "view": "◆",
    "cat": "◆",
    "write_file": "▸",
    "edit": "▸",
    "apply": "▸",
    "patch": "▸",
    "search_files": "◎",
    "grep": "◎",
    "find": "◎",
    "run_command": "▹",
    "execute": "▹",
    "shell": "▹",
    "command": "▹",
    "test": "▪",
    "pytest": "▪",
    "git": "▫",
    "ls": "▫",
    "list": "▫",
}


HELP_TEXT = """\
[bold #22d3ee]◆ JIMMY[/bold #22d3ee]

[b #22d3ee]h[/b #22d3ee]     Toggle help
[b #22d3ee]^x[/b #22d3ee]    Cancel task
[b #22d3ee]^l[/b #22d3ee]    Clear & home
[b #22d3ee]^p[/b #22d3ee]    Permission mode
[b #22d3ee]^q[/b #22d3ee]    Quit

Press [bold]Esc[/bold] or [bold]h[/bold] to close.
"""


class HelpScreen(Screen):
    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape,h", "app.pop_screen", "Close"),
    ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(
                HELP_TEXT,
                id="help-text",
            ),
            id="help-box",
        )

    def on_mount(self) -> None:
        try:
            self.query_one("#help-text", Static).focus()
        except Exception:
            pass


class PermissionScreen(Screen[PermissionMode | None]):
    """Compact permission mode selector."""

    def __init__(
        self,
        current_mode: PermissionMode,
    ) -> None:
        super().__init__()

        self.options = [
            (
                PermissionMode.ASK,
                "🛡",
                "Ask",
                "Approve risky actions",
            ),
            (
                PermissionMode.FULL_ACCESS,
                "⚡",
                "Full Access",
                "Allow tools without asking",
            ),
            (
                PermissionMode.SAFE_ONLY,
                "🔒",
                "Safe Only",
                "Ask before risky actions",
            ),
        ]

        self.selected_index = next(
            (i for i, (mode, _, _, _) in enumerate(self.options) if mode == current_mode),
            0,
        )

    def compose(self) -> ComposeResult:
        yield Center(
            Vertical(
                Static(
                    "🔐  Permission Mode",
                    id="permission-title",
                ),
                Static(
                    "Choose how Jimmy handles risky actions",
                    id="permission-subtitle",
                ),
                Static(
                    "",
                    id="permission-options",
                ),
                Static(
                    "↑↓ select   Enter confirm",
                    id="permission-footer",
                ),
                id="permission-dialog",
            )
        )

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        lines: list[str] = []

        for i, (_, icon, name, description) in enumerate(self.options):
            prefix = "❯" if i == self.selected_index else " "

            lines.append(f"{prefix} {icon}  {name:<13} {description}")

        self.query_one(
            "#permission-options",
            Static,
        ).update("\n".join(lines))

    def on_key(self, event) -> None:
        if event.key in {"up", "k"}:
            self.selected_index = (self.selected_index - 1) % len(self.options)

            self._refresh()

        elif event.key in {"down", "j"}:
            self.selected_index = (self.selected_index + 1) % len(self.options)

            self._refresh()

        elif event.key in {"enter", "return"}:
            self.dismiss(self.options[self.selected_index][0])

        elif event.key == "1":
            self.dismiss(PermissionMode.ASK)

        elif event.key == "2":
            self.dismiss(PermissionMode.FULL_ACCESS)

        elif event.key == "3":
            self.dismiss(PermissionMode.SAFE_ONLY)

        elif event.key == "escape":
            self.dismiss(None)

class PermissionPrompt(Screen[str]):
    """Compact approval dialog for risky actions."""

    def __init__(
        self,
        tool_name: str,
        reason: str,
        arguments: dict[str, Any],
    ) -> None:
        super().__init__()

        self.tool_name = tool_name
        self.reason = reason
        self.arguments = arguments

    def compose(self) -> ComposeResult:
        yield Center(
            Vertical(
                Static(
                    "⚠  Permission Required",
                    id="approval-title",
                ),
                Static(
                    self._tool_text(),
                    id="approval-tool",
                ),
                Static(
                    self.reason,
                    id="approval-reason",
                ),
                Horizontal(
                    Button(
                        "✓ Allow",
                        id="approval-allow",
                        variant="success",
                    ),
                    Button(
                        "✕ Deny",
                        id="approval-deny",
                        variant="error",
                    ),
                    Button(
                        "⚡ Full Access",
                        id="approval-full",
                    ),
                    id="approval-actions",
                ),
                Static(
                    "Y Allow   N Deny   F Full Access",
                    id="approval-footer",
                ),
                id="approval-dialog",
            )
        )

    def _tool_text(self) -> str:
        detail = ""

        for key in (
            "command",
            "path",
            "file_path",
            "query",
        ):
            value = self.arguments.get(key)

            if value is not None:
                detail = str(value)
                break

        if detail:
            return f"Tool   {self.tool_name}\nTarget {detail[:100]}"

        return f"Tool   {self.tool_name}"

    def on_key(self, event) -> None:
        if event.key == "y":
            self.dismiss("allow")

        elif event.key == "n":
            self.dismiss("deny")

        elif event.key == "f":
            self.dismiss("full_access")

        elif event.key == "escape":
            self.dismiss("deny")

    def on_button_pressed(
        self,
        event: Button.Pressed,
    ) -> None:
        if event.button.id == "approval-allow":
            self.dismiss("allow")

        elif event.button.id == "approval-deny":
            self.dismiss("deny")

        elif event.button.id == "approval-full":
            self.dismiss("full_access")

class JimmyTUI(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "Jimmy"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("ctrl+q", "quit_app", "Quit"),
        ("ctrl+x", "cancel_task", "Cancel"),
        ("ctrl+p", "permission_mode", "Permissions"),
        ("h", "show_help", "Help"),
        ("ctrl+l", "clear_conversation", "Clear"),
    ]

    status = reactive("ready")
    permission_mode = reactive(PermissionMode.ASK)
    elapsed = reactive(0.0)
    turn = reactive(0)
    current_tool = reactive("")
    current_file = reactive("")
    running = reactive(False)
    mode = reactive("landing")
    spinner_index = reactive(0)

    def __init__(
        self,
        *,
        agent: Any,
        permission_manager: Any,
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
        self._permission_manager = permission_manager

        self.permission_mode = permission_manager.mode

        self._task_started_at = time.monotonic()
        self._last_error: str | None = None
        self._step_number = 0
        self._worker_cancelled = False
        self._task_generation = 0
        self._current_generation = 0

        self._last_response: str = ""
        self._conversation_history: list[dict[str, str]] = []
        self._files_touched: set[str] = set()

        self._accent_idx = 0
        self._typewriter_idx = 0
        self._typewriter_timer: Any = None
        self._think_idx = 0

        self._git_branch = self._detect_git_branch()

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static("", id="brand"),
            Static("", id="project"),
            Static("", id="file-context"),
            Static("", id="permission-mode"),
            Static("", id="status-indicator"),
            Static("", id="datetime"),
            Static("0.0s", id="clock"),
            id="topbar",
        )

        yield Vertical(
            Static(
                LOGO,
                id="logo-large",
            ),
            Static(
                "",
                id="tagline",
            ),
            Center(
                Input(
                    placeholder="What should Jimmy do?",
                    id="prompt-landing",
                ),
                id="input-wrapper",
            ),
            id="landing-main",
        )

        yield Vertical(
            RichLog(
                id="conversation",
                highlight=False,
                markup=False,
                wrap=True,
                auto_scroll=True,
            ),
            Static(
                "",
                id="typing-indicator",
            ),
            Input(
                placeholder="Ask Jimmy anything...",
                id="prompt-chat",
            ),
            id="chat-main",
        )

        yield Footer()

    def on_mount(self) -> None:
        self._apply_mode(self.mode)
        self._update_brand()
        self._update_project()
        self._update_permission_mode()

        self.set_interval(
            0.08,
            self._tick_fast,
        )
        self.set_interval(
            0.5,
            self._tick_accent,
        )
        self.set_interval(
            1.0,
            self._tick_slow,
        )

        self._focus_input()

        if self._initial_task:
            self._submit_task(
                self._initial_task,
            )
        else:
            self._start_typewriter()

    # ------------------------------------------------------------------
    # TICKS
    # ------------------------------------------------------------------

    def _tick_fast(self) -> None:
        if self.running:
            self.elapsed = time.monotonic() - self._task_started_at

            self.spinner_index = (self.spinner_index + 1) % len(SPINNER_FRAMES)

            self._think_idx = (self._think_idx + 1) % len(THINKING_BAR)

        try:
            self.query_one(
                "#clock",
                Static,
            ).update(self._fmt_dur(self.elapsed))
        except Exception:
            pass

        self._update_status_indicator()

        if self.running:
            bar = THINKING_BAR[self._think_idx]

            try:
                self.query_one(
                    "#typing-indicator",
                    Static,
                ).update(
                    Text(
                        f"{bar}  Jimmy is thinking",
                        style="dim #22d3ee",
                    )
                )
            except Exception:
                pass
        else:
            try:
                self.query_one(
                    "#typing-indicator",
                    Static,
                ).update("")
            except Exception:
                pass

    def _tick_accent(self) -> None:
        self._accent_idx = (self._accent_idx + 1) % 6

        colors = [
            "#22d3ee",
            "#38bdf8",
            "#60a5fa",
            "#818cf8",
            "#a78bfa",
            "#c084fc",
        ]

        color = colors[self._accent_idx]

        if self.mode == "landing":
            try:
                logo = self.query_one(
                    "#logo-large",
                    Static,
                )

                logo.update(
                    Text(
                        LOGO,
                        style=f"bold {color}",
                    )
                )
            except Exception:
                pass

            try:
                inp = self.query_one(
                    "#prompt-landing",
                    Input,
                )

                inp.styles.border = (
                    "solid",
                    color,
                )
            except Exception:
                pass

    def _tick_slow(self) -> None:
        self._update_datetime()

    # ------------------------------------------------------------------
    # TOP BAR
    # ------------------------------------------------------------------

    def _update_brand(self) -> None:
        try:
            self.query_one(
                "#brand",
                Static,
            ).update(
                Text(
                    "◆ JIMMY",
                    style="bold #22d3ee",
                )
            )
        except Exception:
            pass

    def _update_project(self) -> None:
        path_str = str(self._workspace)

        if self._git_branch:
            path_str = f"{path_str} ({self._git_branch})"

        try:
            self.query_one(
                "#project",
                Static,
            ).update(
                Text(
                    path_str,
                    style="#60a5fa",
                )
            )
        except Exception:
            pass

    def _update_permission_mode(self) -> None:
        labels = {
            PermissionMode.ASK: "🛡  Ask",
            PermissionMode.FULL_ACCESS: "⚡ Full Access",
            PermissionMode.SAFE_ONLY: "🔒 Safe Only",
        }

        try:
            self.query_one(
                "#permission-mode",
                Static,
            ).update(
                Text(
                    labels[self._permission_manager.mode],
                    style="bold #fbbf24",
                )
            )
        except Exception:
            pass

    def _update_datetime(self) -> None:
        try:
            self.query_one(
                "#datetime",
                Static,
            ).update(
                Text(
                    self._fmt_datetime(),
                    style="#475569",
                )
            )
        except Exception:
            pass

    def _fmt_datetime(self) -> str:
        now = time.localtime()

        day = str(now.tm_mday)
        mon = time.strftime(
            "%b",
            now,
        )
        year = str(now.tm_year)

        hour = now.tm_hour % 12 or 12

        minute = f"{now.tm_min:02d}"

        ampm = "AM" if now.tm_hour < 12 else "PM"

        return f"{day} {mon} {year} {hour}:{minute} {ampm}"

    @staticmethod
    def _fmt_dur(
        seconds: float,
    ) -> str:
        if seconds < 60:
            return f"{seconds:.1f}s"

        if seconds < 3600:
            m, s = divmod(
                int(seconds),
                60,
            )

            return f"{m}m {s}s"

        h, rem = divmod(
            int(seconds),
            3600,
        )

        m, s = divmod(
            rem,
            60,
        )

        return f"{h}h {m}m {s}s"

    # ------------------------------------------------------------------
    # MODE
    # ------------------------------------------------------------------

    def watch_mode(
        self,
        mode: str,
    ) -> None:
        self._apply_mode(mode)
        self._focus_input()

    def _apply_mode(
        self,
        mode: str,
    ) -> None:
        try:
            screen = self.screen

            screen.remove_class("landing")
            screen.remove_class("chat")

            screen.add_class(mode)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # TYPEWRITER
    # ------------------------------------------------------------------

    def _start_typewriter(self) -> None:
        self._typewriter_idx = 0

        self._typewriter_text = "Terminal-native AI coding assistant"

        self._typewriter_timer = self.set_interval(
            0.04,
            self._typewriter_step,
        )

    def _typewriter_step(self) -> None:
        self._typewriter_idx += 1

        try:
            tagline = self.query_one(
                "#tagline",
                Static,
            )

            if self._typewriter_idx <= len(self._typewriter_text):
                tagline.update(self._typewriter_text[: self._typewriter_idx])
            else:
                if self._typewriter_timer:
                    self._typewriter_timer.stop()

        except Exception:
            if self._typewriter_timer:
                self._typewriter_timer.stop()

    # ------------------------------------------------------------------
    # INPUT
    # ------------------------------------------------------------------

    def on_input_submitted(
        self,
        event: Input.Submitted,
    ) -> None:
        if self.running:
            return

        task = event.value.strip()

        if not task:
            return

        event.input.value = ""

        self._submit_task(task)

    def _focus_input(self) -> None:
        try:
            if self.mode == "landing":
                self.query_one(
                    "#prompt-landing",
                    Input,
                ).focus()
            else:
                self.query_one(
                    "#prompt-chat",
                    Input,
                ).focus()
        except Exception:
            pass

    def _disable_input(self) -> None:
        for iid in (
            "#prompt-landing",
            "#prompt-chat",
        ):
            try:
                self.query_one(
                    iid,
                    Input,
                ).disabled = True
            except Exception:
                pass

    def _enable_input(self) -> None:
        for iid in (
            "#prompt-landing",
            "#prompt-chat",
        ):
            try:
                self.query_one(
                    iid,
                    Input,
                ).disabled = False
            except Exception:
                pass

        self._focus_input()

    # ------------------------------------------------------------------
    # FILE CONTEXT
    # ------------------------------------------------------------------

    def watch_current_file(
        self,
        path: str,
    ) -> None:
        try:
            widget = self.query_one(
                "#file-context",
                Static,
            )

            if path:
                display = path if len(path) < 30 else "…" + path[-27:]

                widget.update(
                    Text(
                        f"◆ {display}",
                        style="#fbbf24",
                    )
                )
            else:
                widget.update("")

        except Exception:
            pass

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------

    def action_focus_input(self) -> None:
        self._focus_input()

    def action_new_task(self) -> None:
        if self.running:
            self.action_cancel_task()

        self._clear_conversation()

        self.mode = "landing"
        self.status = "ready"
        self.current_file = ""

        self._update_status_indicator()
        self._start_typewriter()

    def action_clear_conversation(self) -> None:
        self._clear_conversation()

        if self.mode == "chat":
            self.mode = "landing"

        self.status = "ready"
        self.current_file = ""

        self._update_status_indicator()
        self._start_typewriter()

    def _clear_conversation(self) -> None:
        try:
            self.query_one(
                "#conversation",
                RichLog,
            ).clear()
        except Exception:
            pass

        self._conversation_history.clear()
        self._last_response = ""
        self._files_touched.clear()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_permission_mode(self) -> None:
        self.push_screen(
            PermissionScreen(self._permission_manager.mode),
            self._permission_mode_selected,
        )

    def _permission_mode_selected(
        self,
        mode: PermissionMode | str | None,
    ) -> None:
        if mode is None:
            return

        try:
            if isinstance(mode, str):
                mode = PermissionMode(mode)

            self._permission_manager.set_mode(mode)

            self.permission_mode = mode
            self._update_permission_mode()

        except (ValueError, TypeError):
            pass

    def action_scroll_up(self) -> None:
        try:
            self.query_one(
                "#conversation",
                RichLog,
            ).scroll_up()
        except Exception:
            pass

    def action_scroll_down(self) -> None:
        try:
            self.query_one(
                "#conversation",
                RichLog,
            ).scroll_down()
        except Exception:
            pass

    def action_quit_app(self) -> None:
        self.exit()

    # ------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------

    def _update_status_indicator(self) -> None:
        try:
            self.query_one(
                "#status-indicator",
                Static,
            ).update(self._status_text())
        except Exception:
            pass

    def _status_text(self) -> Text:
        text = Text()

        if self.running:
            frame = SPINNER_FRAMES[self.spinner_index]

            text.append(
                f"{frame} ",
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
    # TASK SUBMISSION
    # ------------------------------------------------------------------

    def _submit_task(
        self,
        task: str,
    ) -> None:
        if self.running:
            return

        self.running = True
        self.status = "thinking"
        self.turn = 0
        self.current_tool = ""
        self.current_file = ""
        self.elapsed = 0.0

        self._task_started_at = time.monotonic()

        self._last_error = None
        self._step_number = 0
        self._worker_cancelled = False

        self._task_generation += 1
        self._current_generation = self._task_generation

        if self._typewriter_timer:
            try:
                self._typewriter_timer.stop()
            except Exception:
                pass

        self.mode = "chat"

        self._write_user_message(task)

        self._update_status_indicator()
        self._disable_input()

        self._start_agent(task)

    # ------------------------------------------------------------------
    # CONVERSATION
    # ------------------------------------------------------------------

    def _write_user_message(
        self,
        message: str,
    ) -> None:
        self._conversation_history.append(
            {
                "role": "user",
                "content": message,
            }
        )

        try:
            log = self.query_one(
                "#conversation",
                RichLog,
            )

            log.write("")
            log.write(
                Text(
                    "▎ YOU",
                    style="bold #22d3ee",
                )
            )

            for line in message.splitlines():
                log.write(
                    Text(
                        f"▎ {line}",
                        style="bold white",
                    )
                )

            log.write("")

        except Exception:
            pass

    def _write_agent_header(self) -> None:
        try:
            log = self.query_one(
                "#conversation",
                RichLog,
            )

            log.write(
                Text(
                    "▎ JIMMY",
                    style="bold #a78bfa",
                )
            )

        except Exception:
            pass

    def _render_content(
        self,
        text: str,
    ) -> None:
        try:
            log = self.query_one(
                "#conversation",
                RichLog,
            )
        except Exception:
            return

        if "```" not in text:
            for line in text.splitlines():
                log.write(
                    Text(
                        f"▎ {line}",
                        style="#d8dee9",
                    )
                )

            return

        parts = re.split(
            r"(```[\w]*\n[\s\S]*?```)",
            text,
        )

        for part in parts:
            if part.startswith("```"):
                lines = part.split("\n")

                lang = lines[0].strip("`").strip() or "text"

                code = "\n".join(lines[1:-1])

                if code:
                    try:
                        syntax = Syntax(
                            code,
                            lang,
                            theme="monokai",
                            background="default",
                        )

                        log.write(syntax)

                    except Exception:
                        for code_line in code.splitlines():
                            log.write(
                                Text(
                                    f"▎ {code_line}",
                                    style="dim",
                                )
                            )

            else:
                for line in part.splitlines():
                    if line.strip():
                        log.write(
                            Text(
                                f"▎ {line}",
                                style="#d8dee9",
                            )
                        )

    def _write_agent_text(
        self,
        text: str,
    ) -> None:
        self._last_response = text

        self._conversation_history.append(
            {
                "role": "assistant",
                "content": text,
            }
        )

        self._render_content(text)

    def _write_tool_start(
        self,
        turn: int,
        tool_name: str | None,
        arguments: dict[str, Any] | None,
    ) -> None:
        try:
            log = self.query_one(
                "#conversation",
                RichLog,
            )

            icon = TOOL_ICONS.get(
                tool_name or "",
                "▪",
            )

            detail = self._tool_detail(arguments)

            t = Text()

            t.append(
                f"  {icon} ",
                style="cyan",
            )

            t.append(
                tool_name or "unknown",
                style="bold white",
            )

            if detail:
                t.append(
                    f"  {detail}",
                    style="dim",
                )

                self._files_touched.add(detail)

            log.write(t)

        except Exception:
            pass

    def _write_tool_end(
        self,
        elapsed: float,
        success: bool,
    ) -> None:
        try:
            log = self.query_one(
                "#conversation",
                RichLog,
            )

            t = Text()

            t.append("    ")

            t.append(
                "✓ " if success else "× ",
                style=("green" if success else "red"),
            )

            t.append(
                self._fmt_dur(elapsed),
                style="dim",
            )

            log.write(t)

        except Exception:
            pass

    def _write_separator(self) -> None:
        try:
            log = self.query_one(
                "#conversation",
                RichLog,
            )

            log.write(
                Text(
                    "─" * 50,
                    style="dim #1e293b",
                )
            )

        except Exception:
            pass

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
        gen = self._current_generation

        try:
            self._agent.run(
                task,
                lambda event: self._agent_event(
                    event,
                    gen,
                ),
                self._ask_permission,
            )

        except (
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            TimeoutError,
            PermissionError,
        ) as exc:
            self.call_from_thread(
                self._agent_failed,
                exc,
                gen,
            )

    def _agent_event(
        self,
        event: AgentEvent,
        generation: int,
    ) -> None:
        self.call_from_thread(
            self._handle_agent_event,
            event,
            generation,
        )

    # ------------------------------------------------------------------
    # PERMISSION
    # ------------------------------------------------------------------

    def _ask_permission(
        self,
        tool_name: str,
        reason: str,
        arguments: dict[str, Any],
    ) -> bool:
        """
        Called from the agent worker thread.

        Show the permission prompt on the Textual UI thread,
        then block this worker until the user answers.
        """

        decision = {
            "approved": False,
        }

        finished = threading.Event()

        def handle_result(
            result: str | None,
        ) -> None:
            if result == "allow":
                decision["approved"] = True

            elif result == "full_access":
                self._permission_manager.set_mode(PermissionMode.FULL_ACCESS)

                self.permission_mode = PermissionMode.FULL_ACCESS

                self._update_permission_mode()

                decision["approved"] = True

            else:
                decision["approved"] = False

            finished.set()

        def show_prompt() -> None:
            if self._worker_cancelled or self._current_generation != self._task_generation:
                decision["approved"] = False
                finished.set()
                return

            self.push_screen(
                PermissionPrompt(
                    tool_name=tool_name,
                    reason=reason,
                    arguments=arguments,
                ),
                handle_result,
            )

        self.call_from_thread(show_prompt)

        finished.wait()

        return decision["approved"]

    # ------------------------------------------------------------------
    # AGENT EVENTS
    # ------------------------------------------------------------------

    def _handle_agent_event(
        self,
        event: AgentEvent,
        generation: int,
    ) -> None:
        if generation != self._current_generation or self._worker_cancelled:
            return

        self.turn = event.turn

        if event.kind == "turn_start":
            self.status = "thinking"
            self.current_tool = ""
            self._update_status_indicator()
            self._write_agent_header()

        elif event.kind == "turn_end":
            if event.message == "final response":
                self.status = "finalizing"

            else:
                self.status = "planning"

                if event.message:
                    self._write_agent_text(event.message)

            self._update_status_indicator()

        elif event.kind == "tool_start":
            self.status = "running"
            self.current_tool = event.tool_name or "unknown"

            detail = self._tool_detail(event.arguments)

            if detail:
                self.current_file = detail

            self._update_status_indicator()

            self._write_tool_start(
                event.turn,
                event.tool_name,
                event.arguments,
            )

        elif event.kind == "tool_end":
            self._step_number += 1

            success = event.message not in {
                "error",
                "denied",
            }

            self._write_tool_end(
                event.elapsed or 0.0,
                success,
            )

            self.current_tool = ""
            self.current_file = ""

            if event.message == "denied":
                self.status = "planning"
            else:
                self.status = "planning" if success else "tool failed"

            self._update_status_indicator()

        elif event.kind == "complete":
            self._task_finished(
                event.message or "",
                event.elapsed,
                generation,
            )

        elif event.kind == "error":
            self._agent_failed(
                RuntimeError(event.message or "Jimmy failed."),
                generation,
            )

    # ------------------------------------------------------------------
    # TASK FINISH
    # ------------------------------------------------------------------

    def _task_finished(
        self,
        result: str,
        elapsed: float | None,
        generation: int,
    ) -> None:
        if generation != self._current_generation:
            return

        self.running = False
        self.status = "ready"
        self.current_tool = ""
        self.current_file = ""

        self.elapsed = elapsed or (time.monotonic() - self._task_started_at)

        if result.strip():
            self._last_response = result.strip()

            self._conversation_history.append(
                {
                    "role": "assistant",
                    "content": result.strip(),
                }
            )

        try:
            log = self.query_one(
                "#conversation",
                RichLog,
            )

            log.write("")

            log.write(
                Text(
                    "▎ ✓ done",
                    style="bold green",
                )
            )

            log.write(
                Text(
                    f"▎ {self._summary()}",
                    style="dim",
                )
            )

            if result.strip():
                log.write("")
                self._render_content(result.strip())

            log.write("")
            self._write_separator()

        except Exception:
            pass

        self._enable_input()
        self._update_status_indicator()

    # ------------------------------------------------------------------
    # ERROR
    # ------------------------------------------------------------------

    def _agent_failed(
        self,
        exc: Exception,
        generation: int,
    ) -> None:
        if generation != self._current_generation:
            return

        self.running = False
        self.status = "error"
        self.current_tool = ""
        self.current_file = ""
        self._last_error = str(exc)

        self.elapsed = time.monotonic() - self._task_started_at

        try:
            log = self.query_one(
                "#conversation",
                RichLog,
            )

            log.write("")

            log.write(
                Text(
                    f"▎ × {type(exc).__name__}: {exc}",
                    style="bold red",
                )
            )

            log.write(
                Text(
                    f"▎ {self._summary()}",
                    style="dim",
                )
            )

            log.write("")

        except Exception:
            pass

        self._enable_input()
        self._update_status_indicator()

    # ------------------------------------------------------------------
    # CANCEL
    # ------------------------------------------------------------------

    def action_cancel_task(self) -> None:
        if not self.running:
            return

        self._worker_cancelled = True

        try:
            for worker in self.workers:
                if worker.group == "agent":
                    worker.cancel()
        except Exception:
            pass

        self.running = False
        self.status = "ready"
        self.current_tool = ""
        self.current_file = ""

        try:
            log = self.query_one(
                "#conversation",
                RichLog,
            )

            log.write("")

            log.write(
                Text(
                    "▎ task cancelled",
                    style="yellow",
                )
            )

            log.write("")

        except Exception:
            pass

        self._enable_input()
        self._update_status_indicator()

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

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
                return str(value).replace("\n", " ")[:90]

        return ""

    def _summary(self) -> str:
        return "  ·  ".join(
            [
                self._fmt_dur(self.elapsed),
                f"{self._step_number} tools",
                f"{len(self._files_touched)} files",
                f"turn {self.turn}",
            ]
        )

    def _detect_git_branch(self) -> str:
        try:
            result = subprocess.run(
                [
                    "git",
                    "rev-parse",
                    "--abbrev-ref",
                    "HEAD",
                ],
                cwd=self._workspace,
                capture_output=True,
                text=True,
                timeout=2,
            )

            if result.returncode == 0:
                return result.stdout.strip()

        except Exception:
            pass

        return ""


def run_tui(
    *,
    agent: Any,
    permission_manager: Any,
    initial_task: str | None,
    version: str,
    workspace: Path,
    show_time: bool = False,
) -> None:
    app = JimmyTUI(
        agent=agent,
        permission_manager=permission_manager,
        initial_task=initial_task,
        version=version,
        workspace=workspace,
        show_time=show_time,
    )

    app.run(mouse=True)
