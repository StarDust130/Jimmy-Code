from __future__ import annotations

import re
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from rich.syntax import Syntax
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.message import Message
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
[b #22d3ee]^l[/b #22d3ee]    Clear input
[b #22d3ee]^n[/b #22d3ee]    New task
[b #22d3ee]^p[/b #22d3ee]    Permission mode
[b #22d3ee]^q[/b #22d3ee]    Quit

Press [bold]Esc[/bold] or [bold]h[/bold] to close.
"""


# ═════════════════════════════════════════════════════════════
# SESSION WIDGETS
# ═════════════════════════════════════════════════════════════


class SessionCard(Static):
    can_focus = True

    class Selected(Message):
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    def __init__(self, session: dict, **kwargs: Any) -> None:
        self.session = session
        kwargs.setdefault("classes", "session-card")
        super().__init__(**kwargs)

    def on_mount(self) -> None:
        self.update(self._render_text())

    def _render_text(self) -> Text:
        t = Text()
        title = self.session.get("task", "Untitled")
        if len(title) > 46:
            title = title[:43] + "…"
        status = self.session.get("status", "unknown")
        status_icon = "✓" if status == "completed" else "○"
        status_color = "#4ade80" if status == "completed" else "#60a5fa"
        status_text = "Completed" if status == "completed" else "Active"
        turn_count = self.session.get("turn_count", 0)
        updated_at = self.session.get("updated_at", "")
        ago = self._time_ago(updated_at)
        t.append(f"{title}\n", style="bold #e0f2fe")
        t.append(f"{status_icon} ", style=status_color)
        t.append(f"{status_text}  ·  {turn_count} turns  ·  {ago}", style="dim #94a3b8")
        return t

    def _time_ago(self, iso_str: str) -> str:
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            diff = datetime.now(UTC) - dt
            seconds = diff.total_seconds()
            if seconds < 60:
                return "just now"
            elif seconds < 3600:
                return f"{int(seconds // 60)}m ago"
            elif seconds < 86400:
                return f"{int(seconds // 3600)}h ago"
            else:
                return f"{int(seconds // 86400)}d ago"
        except Exception:
            return ""

    def on_click(self) -> None:
        self.post_message(self.Selected(self.session.get("id", "")))


class ViewAllLink(Static):
    class ShowAll(Message):
        pass

    def __init__(self) -> None:
        super().__init__("View all →", classes="view-all-link")

    def on_click(self) -> None:
        self.post_message(self.ShowAll())


class DeleteButton(Static):
    class Pressed(Message):
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    def __init__(self, session_id: str, **kwargs: Any) -> None:
        self.session_id = session_id
        kwargs.setdefault("classes", "delete-button")
        super().__init__("×", **kwargs)

    def on_click(self) -> None:
        self.post_message(self.Pressed(self.session_id))


class DeleteConfirmScreen(Screen[bool]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("y,enter", "confirm", "", show=False),
        Binding("n,escape", "cancel", "", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Center(
            Vertical(
                Static("Delete this session?", id="delete-title"),
                Horizontal(
                    Button("Delete", id="delete-confirm", variant="error"),
                    Button("Cancel", id="delete-cancel", variant="primary"),
                    id="delete-actions",
                ),
                id="delete-dialog",
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "delete-confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_key(self, event: Any) -> None:
        if event.key in {"y", "enter"}:
            self.dismiss(True)
        elif event.key in {"n", "escape"}:
            self.dismiss(False)


class AllSessionsScreen(Screen[str | None]):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("up,k", "select_prev", "", show=False),
        Binding("down,j", "select_next", "", show=False),
        Binding("enter", "select_open", "", show=False),
        Binding("escape", "close_dialog", "", show=False),
    ]

    def __init__(
        self,
        sessions: list[dict],
        current_session_id: str | None = None,
    ) -> None:
        super().__init__()
        self.sessions = sessions
        self.current_session_id = current_session_id
        self.selected_index = 0
        if current_session_id:
            for i, s in enumerate(sessions):
                if s.get("id") == current_session_id:
                    self.selected_index = i
                    break

    def compose(self) -> ComposeResult:
        with Vertical(id="all-sessions-dialog"):
            yield Static("All Sessions", id="all-sessions-title")
            with Vertical(id="all-sessions-list"):
                for session in self.sessions:
                    yield SessionCard(session, classes="all-session-card")
            yield Static(
                "↑↓ select · Enter open · Esc close",
                id="all-sessions-footer",
            )

    def on_mount(self) -> None:
        self._update_selection()

    def _update_selection(self) -> None:
        cards = list(self.query(".all-session-card"))
        for i, card in enumerate(cards):
            if i == self.selected_index:
                card.add_class("selected")
                card.scroll_visible()
            else:
                card.remove_class("selected")

    def action_select_prev(self) -> None:
        self.selected_index = max(0, self.selected_index - 1)
        self._update_selection()

    def action_select_next(self) -> None:
        self.selected_index = min(len(self.sessions) - 1, self.selected_index + 1)
        self._update_selection()

    def action_select_open(self) -> None:
        if 0 <= self.selected_index < len(self.sessions):
            self.dismiss(self.sessions[self.selected_index].get("id"))

    def action_close_dialog(self) -> None:
        self.dismiss(None)

    def on_session_card_selected(self, event: SessionCard.Selected) -> None:
        self.dismiss(event.session_id)
        event.stop()


# ═════════════════════════════════════════════════════════════
# HELP & PERMISSION SCREENS
# ═════════════════════════════════════════════════════════════


class HelpScreen(Screen):
    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape,h", "app.pop_screen", "Close"),
    ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(HELP_TEXT, id="help-text"),
            id="help-box",
        )

    def on_mount(self) -> None:
        try:
            self.query_one("#help-text", Static).focus()
        except Exception:
            pass


class PermissionScreen(Screen[PermissionMode | None]):
    def __init__(self, current_mode: PermissionMode) -> None:
        super().__init__()
        self.options = [
            (
                PermissionMode.SAFE_ONLY,
                "🔒",
                "Safe Only",
                "Read/search freely • approve edits & commands",
            ),
            (
                PermissionMode.ASK,
                "🛡",
                "Ask",
                "Work normally • approve risky actions",
            ),
            (
                PermissionMode.FULL_ACCESS,
                "⚡",
                "Full Access",
                "Allow every tool without prompts",
            ),
        ]
        self.selected_index = next(
            (i for i, (mode, _, _, _) in enumerate(self.options) if mode == current_mode),
            1,
        )

    def compose(self) -> ComposeResult:
        yield Center(
            Vertical(
                Static("🔐  Permission Mode", id="permission-title"),
                Static(
                    "Choose how Jimmy should handle tool permissions.",
                    id="permission-subtitle",
                ),
                Static("", id="permission-options"),
                Static(
                    "↑↓ select   Enter confirm   Esc close",
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
        self.query_one("#permission-options", Static).update("\n".join(lines))

    def on_key(self, event: Any) -> None:
        if event.key in {"up", "k"}:
            self.selected_index = (self.selected_index - 1) % len(self.options)
            self._refresh()
        elif event.key in {"down", "j"}:
            self.selected_index = (self.selected_index + 1) % len(self.options)
            self._refresh()
        elif event.key in {"enter", "return"}:
            self.dismiss(self.options[self.selected_index][0])
        elif event.key == "1":
            self.dismiss(PermissionMode.SAFE_ONLY)
        elif event.key == "2":
            self.dismiss(PermissionMode.ASK)
        elif event.key == "3":
            self.dismiss(PermissionMode.FULL_ACCESS)
        elif event.key == "escape":
            self.dismiss(None)


class PermissionPrompt(Screen[str]):
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
                Static("⚠  Permission Required", id="approval-title"),
                Static(self._tool_text(), id="approval-tool"),
                Static(self.reason, id="approval-reason"),
                Horizontal(
                    Button("✓ Allow", id="approval-allow", variant="success"),
                    Button("✕ Deny", id="approval-deny", variant="error"),
                    Button("⚡ Full Access", id="approval-full"),
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
        for key in ("command", "path", "file_path", "query"):
            value = self.arguments.get(key)
            if value is not None:
                detail = str(value)
                break
        if detail:
            return f"Tool   {self.tool_name}\nTarget {detail[:100]}"
        return f"Tool   {self.tool_name}"

    def on_key(self, event: Any) -> None:
        if event.key == "y":
            self.dismiss("allow")
        elif event.key == "n":
            self.dismiss("deny")
        elif event.key == "f":
            self.dismiss("full_access")
        elif event.key == "escape":
            self.dismiss("deny")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "approval-allow":
            self.dismiss("allow")
        elif event.button.id == "approval-deny":
            self.dismiss("deny")
        elif event.button.id == "approval-full":
            self.dismiss("full_access")


# ═════════════════════════════════════════════════════════════
# MAIN APP
# ═════════════════════════════════════════════════════════════


class JimmyTUI(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "Jimmy"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+q", "quit_app", "Quit"),
        Binding("ctrl+x", "cancel_task", "Cancel"),
        Binding("ctrl+p", "permission_mode", "Permissions"),
        Binding("h", "show_help", "Help"),
        Binding("ctrl+l", "clear_input", "Clear"),
        Binding("ctrl+n", "new_task", "New Task"),
        Binding("ctrl+shift+c", "copy_response", "", show=False),
        Binding("ctrl+shift+u", "copy_prompt", "", show=False),
        Binding("ctrl+shift+a", "copy_conversation", "", show=False),
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
    observability_model = reactive("Jimmy")
    observability_turns = reactive(0)
    observability_tools = reactive(0)
    observability_input_tokens = reactive(0)
    observability_output_tokens = reactive(0)
    observability_total_tokens = reactive(0)
    observability_cost = reactive(0.0)

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

        llm = getattr(agent, "llm", None)
        self.observability_model = getattr(
            llm,
            "model",
            type(llm).__name__ if llm is not None else "Jimmy",
        )
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

        # Session state
        self._current_session_id: str | None = None
        self._current_task: str | None = None
        self._agent_header_needed = False

        # Input history
        self._prompt_history: list[str] = []
        self._history_pos: int = -1
        self._history_draft: str = ""

    def compose(self) -> ComposeResult:
        # Fixed header stays visible while chat content scrolls.
        yield Horizontal(
            Static("", id="brand"),
            Static("", id="project"),
            Static("", id="session-indicator"),
            Static("", id="file-context"),
            Static("", id="permission-mode"),
            Static("", id="status-indicator"),
            Static("", id="datetime"),
            Static("0.0s", id="clock"),
            id="topbar",
        )

        # Landing screen. Hidden automatically in chat mode.
        yield Vertical(
            Static(LOGO, id="logo-large"),
            Static("", id="tagline"),
            Center(
                Input(
                    placeholder="What should Jimmy do?",
                    id="prompt-landing",
                ),
                id="input-wrapper",
            ),
            Center(
                Vertical(
                    Static(
                        "Recent Sessions",
                        classes="recent-sessions-header",
                    ),
                    Vertical(id="recent-sessions-list"),
                    id="recent-sessions-container",
                ),
                id="recent-sessions-wrapper",
            ),
            id="landing-main",
        )

        # Chat area. Observability sits directly under the conversation.
        yield Vertical(
            RichLog(
                id="conversation",
                highlight=False,
                markup=False,
                wrap=True,
                auto_scroll=True,
            ),
            Static("", id="observability"),
            Static("", id="typing-indicator"),
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
        self._update_session_indicator()
        self._refresh_landing_sessions()
        self._update_observability()

        self.set_interval(0.08, self._tick_fast)
        self.set_interval(0.5, self._tick_accent)
        self.set_interval(1.0, self._tick_slow)

        self._focus_input()

        if self._initial_task:
            self._submit_task(self._initial_task)
        else:
            self._start_typewriter()

    # ------------------------------------------------------------------
    # KEYS — input history & copy
    # ------------------------------------------------------------------

    def on_key(self, event: Any) -> None:
        if event.key == "up" and isinstance(self.focused, Input):
            self._history_prev()
            event.stop()
        elif event.key == "down" and isinstance(self.focused, Input):
            self._history_next()
            event.stop()

    def _history_prev(self) -> None:
        if not self._prompt_history:
            return
        focused = self.focused
        if not isinstance(focused, Input):
            return
        if self._history_pos == -1:
            self._history_draft = focused.value or ""
        if self._history_pos < len(self._prompt_history) - 1:
            self._history_pos += 1
            value = self._prompt_history[-(self._history_pos + 1)]
            self._set_input_value(value)

    def _history_next(self) -> None:
        focused = self.focused
        if not isinstance(focused, Input):
            return
        if self._history_pos <= 0:
            self._history_pos = -1
            self._set_input_value(self._history_draft)
        elif self._history_pos > 0:
            self._history_pos -= 1
            value = self._prompt_history[-(self._history_pos + 1)]
            self._set_input_value(value)

    def _set_input_value(self, value: str) -> None:
        try:
            if self.mode == "landing":
                inp = self.query_one("#prompt-landing", Input)
            else:
                inp = self.query_one("#prompt-chat", Input)
            inp.value = value
            inp.cursor_position = len(value)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # COPY
    # ------------------------------------------------------------------

    def action_copy_response(self) -> None:
        if self._last_response:
            self._copy_text(self._last_response, "Response copied")
        else:
            self._notify("No response to copy", "warning")

    def action_copy_prompt(self) -> None:
        for msg in reversed(self._conversation_history):
            if msg.get("role") == "user":
                self._copy_text(msg.get("content", ""), "Prompt copied")
                return
        self._notify("No prompt to copy", "warning")

    def action_copy_conversation(self) -> None:
        if not self._conversation_history:
            self._notify("No conversation to copy", "warning")
            return
        lines: list[str] = []
        for msg in self._conversation_history:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"YOU:\n{content}")
            elif role == "assistant":
                lines.append(f"JIMMY:\n{content}")
            lines.append("")
        text = "\n".join(lines).strip()
        if text:
            self._copy_text(text, "Conversation copied")
        else:
            self._notify("No conversation to copy", "warning")

    def _copy_text(self, text: str, success_msg: str) -> None:
        import platform

        system = platform.system()
        try:
            if system == "Windows":
                subprocess.run(["clip"], input=text, text=True, check=True, timeout=2)
            elif system == "Darwin":
                subprocess.run(["pbcopy"], input=text, text=True, check=True, timeout=2)
            else:
                try:
                    subprocess.run(["wl-copy"], input=text, text=True, check=True, timeout=2)
                except (FileNotFoundError, subprocess.CalledProcessError):
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"],
                        input=text,
                        text=True,
                        check=True,
                        timeout=2,
                    )
            self._notify(success_msg, "information")
        except Exception:
            self._notify(
                "Copy failed — select text with Shift+mouse and copy via terminal",
                "warning",
            )

    def _notify(self, message: str, severity: str) -> None:
        try:
            self.notify(message, severity=severity, timeout=1.5)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # TICKS
    # ------------------------------------------------------------------

    def _tick_fast(self) -> None:
        if self.running:
            self.elapsed = time.monotonic() - self._task_started_at
            self.spinner_index = (self.spinner_index + 1) % len(SPINNER_FRAMES)
            self._think_idx = (self._think_idx + 1) % len(THINKING_BAR)

        try:
            self.query_one("#clock", Static).update(self._fmt_dur(self.elapsed))
        except Exception:
            pass

        self._update_status_indicator()
        self._update_observability()

        if self.running:
            bar = THINKING_BAR[self._think_idx]
            try:
                self.query_one("#typing-indicator", Static).update(
                    Text(f"{bar}  Jimmy is thinking", style="dim #22d3ee")
                )
            except Exception:
                pass
        else:
            try:
                self.query_one("#typing-indicator", Static).update("")
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
                logo = self.query_one("#logo-large", Static)
                logo.update(Text(LOGO, style=f"bold {color}"))
            except Exception:
                pass

            try:
                inp = self.query_one("#prompt-landing", Input)
                inp.styles.border = ("solid", color)
            except Exception:
                pass

    def _tick_slow(self) -> None:
        self._update_datetime()

    # ------------------------------------------------------------------
    # TOP BAR
    # ------------------------------------------------------------------

    def _update_brand(self) -> None:
        try:
            self.query_one("#brand", Static).update(Text("◆ JIMMY", style="bold #22d3ee"))
        except Exception:
            pass

    def _update_project(self) -> None:
        path_str = str(self._workspace)
        if self._git_branch:
            path_str = f"{path_str} ({self._git_branch})"
        try:
            self.query_one("#project", Static).update(Text(path_str, style="#60a5fa"))
        except Exception:
            pass

    def _update_permission_mode(self) -> None:
        labels = {
            PermissionMode.ASK: "🛡  Ask",
            PermissionMode.FULL_ACCESS: "⚡ Full Access",
            PermissionMode.SAFE_ONLY: "🔒 Safe Only",
        }
        try:
            self.query_one("#permission-mode", Static).update(
                Text(labels[self._permission_manager.mode], style="bold #fbbf24")
            )
        except Exception:
            pass

    def _update_session_indicator(self) -> None:
        try:
            widget = self.query_one("#session-indicator", Static)
            if self._current_session_id and self._current_task:
                title = self._current_task
                if len(title) > 25:
                    title = title[:22] + "…"
                widget.update(Text(f"◈ {title}", style="#c4b5fd"))
            else:
                widget.update("")
        except Exception:
            pass

    def _update_datetime(self) -> None:
        try:
            self.query_one("#datetime", Static).update(Text(self._fmt_datetime(), style="#475569"))
        except Exception:
            pass

    def _fmt_datetime(self) -> str:
        now = time.localtime()
        day = str(now.tm_mday)
        mon = time.strftime("%b", now)
        year = str(now.tm_year)
        hour = now.tm_hour % 12 or 12
        minute = f"{now.tm_min:02d}"
        ampm = "AM" if now.tm_hour < 12 else "PM"
        return f"{day} {mon} {year} {hour}:{minute} {ampm}"

    @staticmethod
    def _fmt_dur(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f}s"
        if seconds < 3600:
            m, s = divmod(int(seconds), 60)
            return f"{m}m {s}s"
        h, rem = divmod(int(seconds), 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m {s}s"

    # ------------------------------------------------------------------
    # MODE
    # ------------------------------------------------------------------

    def watch_mode(self, mode: str) -> None:
        self._apply_mode(mode)
        self._focus_input()
        if mode == "landing":
            self._refresh_landing_sessions()

    def _apply_mode(self, mode: str) -> None:
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
        self._typewriter_timer = self.set_interval(0.04, self._typewriter_step)

    def _typewriter_step(self) -> None:
        self._typewriter_idx += 1
        try:
            tagline = self.query_one("#tagline", Static)
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.running:
            return
        task = event.value.strip()
        if not task:
            return
        event.input.value = ""

        # Save to history
        if not self._prompt_history or self._prompt_history[-1] != task:
            self._prompt_history.append(task)
        self._history_pos = -1
        self._history_draft = ""

        self._submit_task(task)

    def _focus_input(self) -> None:
        try:
            if self.mode == "landing":
                self.query_one("#prompt-landing", Input).focus()
            else:
                self.query_one("#prompt-chat", Input).focus()
        except Exception:
            pass

    def _disable_input(self) -> None:
        for iid in ("#prompt-landing", "#prompt-chat"):
            try:
                self.query_one(iid, Input).disabled = True
            except Exception:
                pass

    def _enable_input(self) -> None:
        for iid in ("#prompt-landing", "#prompt-chat"):
            try:
                self.query_one(iid, Input).disabled = False
            except Exception:
                pass
        self._focus_input()

    # ------------------------------------------------------------------
    # FILE CONTEXT
    # ------------------------------------------------------------------

    def watch_current_file(self, path: str) -> None:
        try:
            widget = self.query_one("#file-context", Static)
            if path:
                display = path if len(path) < 30 else "…" + path[-27:]
                widget.update(Text(f"◆ {display}", style="#fbbf24"))
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
        self.current_tool = ""
        self.turn = 0
        self._step_number = 0
        self.elapsed = 0.0
        self._last_error = None
        self._reset_observability()
        self._current_session_id = None
        self._current_task = None
        self._history_pos = -1
        self._history_draft = ""
        self._update_status_indicator()
        self._update_session_indicator()
        self._start_typewriter()
        self._focus_input()
        self._refresh_landing_sessions()

    def action_clear_input(self) -> None:
        if self.mode == "landing":
            try:
                inp = self.query_one("#prompt-landing", Input)
                inp.value = ""
                inp.focus()
            except Exception:
                pass
        else:
            try:
                inp = self.query_one("#prompt-chat", Input)
                inp.value = ""
                inp.focus()
            except Exception:
                pass

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
            self.query_one("#conversation", RichLog).scroll_up()
        except Exception:
            pass

    def action_scroll_down(self) -> None:
        try:
            self.query_one("#conversation", RichLog).scroll_down()
        except Exception:
            pass

    def action_quit_app(self) -> None:
        self.exit()

    # ------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------

    def _update_status_indicator(self) -> None:
        try:
            self.query_one("#status-indicator", Static).update(self._status_text())
        except Exception:
            pass

    def _status_text(self) -> Text:
        text = Text()
        if self.running:
            frame = SPINNER_FRAMES[self.spinner_index]
            text.append(f"{frame} ", style="cyan")
            text.append(self.status, style="bold white")
        elif self.status == "error":
            text.append("× ", style="bold red")
            text.append("error", style="bold red")
        else:
            text.append("› ", style="green")
            text.append("ready", style="bold green")

        if self.turn:
            text.append(f"  ·  turn {self.turn}", style="dim")
        if self.current_tool:
            text.append("  ·  ", style="dim")
            text.append(self.current_tool, style="cyan")
        return text

    # ------------------------------------------------------------------
    # SESSIONS
    # ------------------------------------------------------------------

    def _refresh_landing_sessions(self) -> None:
        try:
            container = self.query_one("#recent-sessions-list", Vertical)
            for child in list(container.children):
                child.remove()
        except Exception:
            return

        try:
            wrapper = self.query_one("#recent-sessions-wrapper", Center)
        except Exception:
            return

        sessions: list[dict] = []
        try:
            store = getattr(self._agent, "session_store", None)
            if store is not None:
                sessions = store.list()
        except Exception:
            pass

        if not sessions:
            wrapper.styles.display = "none"
            return

        wrapper.styles.display = "block"

        for session in sessions[:3]:
            try:
                row = Horizontal(classes="session-row")
                container.mount(row)
                row.mount(SessionCard(session))
                row.mount(DeleteButton(session.get("id", "")))
            except Exception:
                pass

        if len(sessions) > 3:
            try:
                container.mount(ViewAllLink())
            except Exception:
                pass

    def _show_all_sessions(self) -> None:
        sessions: list[dict] = []
        try:
            store = getattr(self._agent, "session_store", None)
            if store is not None:
                sessions = store.list()
        except Exception:
            pass
        if not sessions:
            return

        def handle_selection(result: str | None) -> None:
            if result:
                self._resume_session(result)

        self.push_screen(
            AllSessionsScreen(sessions, self._current_session_id),
            handle_selection,
        )

    def _resume_session(self, session_id: str) -> None:
        if self.running:
            return

        try:
            store = getattr(self._agent, "session_store", None)
            if store is None:
                return
            state = store.load(session_id)
        except Exception:
            return

        self._current_session_id = session_id
        self._current_task = getattr(state, "task", "Session")
        self._conversation_history = []
        self._files_touched = set()
        self._last_response = ""
        self._step_number = 0
        self.turn = getattr(state, "turn_count", 0)

        self._clear_conversation()

        for msg in getattr(state, "messages", []):
            role = msg.get("role")
            if role == "user":
                self._conversation_history.append(
                    {"role": "user", "content": msg.get("content", "")}
                )
                self._render_user_message(msg.get("content", ""))
            elif role == "assistant":
                self._conversation_history.append(
                    {"role": "assistant", "content": msg.get("content", "")}
                )
                self._render_agent_header()
                self._render_content(msg.get("content", ""))

        try:
            log = self.query_one("#conversation", RichLog)
            log.scroll_end()
        except Exception:
            pass

        self.mode = "chat"
        self.status = "ready"
        self.current_tool = ""
        self.current_file = ""
        self._update_status_indicator()
        self._update_session_indicator()
        self._enable_input()
        self._focus_input()

    def _render_user_message(self, message: str) -> None:
        try:
            log = self.query_one("#conversation", RichLog)
            log.write("")
            log.write(Text("▎ YOU", style="bold #22d3ee"))
            for line in message.splitlines():
                log.write(Text(f"▎ {line}", style="bold white"))
            log.write("")
        except Exception:
            pass

    def _render_agent_header(self) -> None:
        try:
            log = self.query_one("#conversation", RichLog)
            log.write(Text("▎ JIMMY", style="bold #a78bfa"))
        except Exception:
            pass

    def _ensure_agent_header(self) -> None:
        if self._agent_header_needed:
            self._render_agent_header()
            self._agent_header_needed = False

    def on_view_all_link_show_all(self, event: ViewAllLink.ShowAll) -> None:
        self._show_all_sessions()

    def on_session_card_selected(self, event: SessionCard.Selected) -> None:
        if isinstance(self.screen, AllSessionsScreen):
            return
        self._resume_session(event.session_id)

    def on_delete_button_pressed(self, event: DeleteButton.Pressed) -> None:
        self._confirm_delete_session(event.session_id)

    def _confirm_delete_session(self, session_id: str) -> None:
        def handle_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._delete_session(session_id)

        self.push_screen(DeleteConfirmScreen(), handle_confirm)

    def _delete_session(self, session_id: str) -> None:
        try:
            store = getattr(self._agent, "session_store", None)
            if store is not None:
                store.delete(session_id)
        except Exception:
            self._notify("Failed to delete session", "error")
            return

        if self._current_session_id == session_id:
            self.action_new_task()
        else:
            self._refresh_landing_sessions()

    # ------------------------------------------------------------------
    # TASK SUBMISSION
    # ------------------------------------------------------------------

    def _submit_task(self, task: str) -> None:
        if self.running:
            return

        self.running = True
        self.status = "thinking"
        self.current_tool = ""
        self.current_file = ""
        self.elapsed = 0.0
        self._task_started_at = time.monotonic()
        self._last_error = None
        self._reset_observability()
        self._step_number = 0
        self._worker_cancelled = False
        self._task_generation += 1
        self._current_generation = self._task_generation

        if self._typewriter_timer:
            try:
                self._typewriter_timer.stop()
            except Exception:
                pass

        self._current_task = task
        self.mode = "chat"

        if self._current_session_id:
            try:
                store = getattr(self._agent, "session_store", None)
                if store is not None:
                    state = store.load(self._current_session_id)
                    state.add_message({"role": "user", "content": task})
                    store.save(self._current_session_id, state, "running")
            except Exception:
                pass
            self._write_user_message(task)
            self._update_status_indicator()
            self._disable_input()
            self._start_agent_resume(self._current_session_id)
        else:
            self._write_user_message(task)
            self._update_status_indicator()
            self._disable_input()
            self._start_agent(task)

    # ------------------------------------------------------------------
    # CONVERSATION
    # ------------------------------------------------------------------

    def _write_user_message(self, message: str) -> None:
        self._conversation_history.append({"role": "user", "content": message})
        self._render_user_message(message)

    def _write_agent_text(self, text: str) -> None:
        self._last_response = text
        self._conversation_history.append({"role": "assistant", "content": text})
        self._render_content(text)

    def _render_content(self, text: str) -> None:
        try:
            log = self.query_one("#conversation", RichLog)
        except Exception:
            return

        if "```" not in text:
            for line in text.splitlines():
                log.write(Text(f"▎ {line}", style="#d8dee9"))
            return

        parts = re.split(r"(```[\w]*\n[\s\S]*?```)", text)
        for part in parts:
            if part.startswith("```"):
                lines = part.split("\n")
                lang = lines[0].strip("`").strip() or "text"
                code = "\n".join(lines[1:-1])
                if code:
                    try:
                        syntax = Syntax(code, lang, theme="monokai")
                        log.write(syntax)
                    except Exception:
                        for code_line in code.splitlines():
                            log.write(Text(f"▎ {code_line}", style="dim"))
            else:
                for line in part.splitlines():
                    if line.strip():
                        log.write(Text(f"▎ {line}", style="#d8dee9"))

    def _write_tool_start(
        self,
        turn: int,
        tool_name: str | None,
        arguments: dict[str, Any] | None,
    ) -> None:
        try:
            log = self.query_one("#conversation", RichLog)
            icon = TOOL_ICONS.get(tool_name or "", "▪")
            detail = self._tool_detail(arguments)
            t = Text()
            t.append(f"  {icon} ", style="cyan")
            t.append(tool_name or "unknown", style="bold white")
            if detail:
                t.append(f"  {detail}", style="dim")
                self._files_touched.add(detail)
            log.write(t)
        except Exception:
            pass

    def _write_tool_end(self, elapsed: float, success: bool) -> None:
        try:
            log = self.query_one("#conversation", RichLog)
            t = Text()
            t.append("    ")
            t.append("✓ " if success else "× ", style=("green" if success else "red"))
            t.append(self._fmt_dur(elapsed), style="dim")
            log.write(t)
        except Exception:
            pass

    def _write_separator(self) -> None:
        try:
            log = self.query_one("#conversation", RichLog)
            log.write(Text("─" * 50, style="dim #1e293b"))
        except Exception:
            pass

    def _clear_conversation(self) -> None:
        try:
            self.query_one("#conversation", RichLog).clear()
        except Exception:
            pass
        self._conversation_history.clear()
        self._last_response = ""
        self._files_touched.clear()

    # ------------------------------------------------------------------
    # AGENT WORKER
    # ------------------------------------------------------------------

    @work(thread=True, group="agent", exclusive=True, exit_on_error=False)
    def _start_agent(self, task: str) -> None:
        gen = self._current_generation
        try:
            self._agent.run(
                task,
                lambda event: self._agent_event(event, gen),
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
            self.call_from_thread(self._agent_failed, exc, gen)

    @work(thread=True, group="agent", exclusive=True, exit_on_error=False)
    def _start_agent_resume(self, session_id: str) -> None:
        gen = self._current_generation
        try:
            self._agent.resume(
                session_id,
                lambda event: self._agent_event(event, gen),
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
            self.call_from_thread(self._agent_failed, exc, gen)

    def _agent_event(self, event: AgentEvent, generation: int) -> None:
        self.call_from_thread(self._handle_agent_event, event, generation)

    # ------------------------------------------------------------------
    # PERMISSION
    # ------------------------------------------------------------------

    def _ask_permission(
        self,
        tool_name: str,
        reason: str,
        arguments: dict[str, Any],
    ) -> bool:
        decision = {"approved": False}
        finished = threading.Event()

        def handle_result(result: str | None) -> None:
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
        self.observability_turns = event.turn

        if event.kind == "turn_start":
            self.status = "thinking"
            self.current_tool = ""

        elif event.kind == "turn_end":
            if event.message == "final response":
                self.status = "finalizing"
            else:
                self.status = "planning"

        elif event.kind == "llm_usage":
            self.observability_model = event.model_name or event.message or self.observability_model
            self.observability_input_tokens = event.input_tokens or 0
            self.observability_output_tokens = event.output_tokens or 0
            self.observability_total_tokens = event.total_tokens or 0
            if event.cost_usd is not None:
                self.observability_cost += event.cost_usd

        elif event.kind == "tool_start":
            self.status = "running"
            self.current_tool = event.tool_name or "unknown"

            self.observability_tools += 1

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

        elif event.kind == "complete":
            self._task_finished(
                event.message or "",
                event.elapsed,
                generation,
            )

        elif event.kind == "error":
            self._last_error = event.message or "Jimmy failed."
            self._agent_failed(
                RuntimeError(self._last_error),
                generation,
            )

        self._update_observability()
        self._update_status_indicator()

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
            self._conversation_history.append({"role": "assistant", "content": result.strip()})

        try:
            log = self.query_one("#conversation", RichLog)
            log.write("")
            log.write(Text("▎ ✓ done", style="bold green"))
            log.write(Text(f"▎ {self._summary()}", style="dim"))
            if result.strip():
                log.write("")
                self._ensure_agent_header()
                self._render_content(result.strip())
            log.write("")
            self._write_separator()
        except Exception:
            pass

        self._enable_input()
        self._update_observability()
        self._update_status_indicator()
        self._update_session_indicator()
        self._refresh_landing_sessions()

    # ------------------------------------------------------------------
    # ERROR
    # ------------------------------------------------------------------

    def _agent_failed(self, exc: Exception, generation: int) -> None:
        if generation != self._current_generation:
            return

        self.running = False
        self.status = "error"
        self.current_tool = ""
        self.current_file = ""
        self._last_error = str(exc)
        self.elapsed = time.monotonic() - self._task_started_at

        try:
            log = self.query_one("#conversation", RichLog)
            log.write("")
            log.write(Text(f"▎ × {type(exc).__name__}: {exc}", style="bold red"))
            log.write(Text(f"▎ {self._summary()}", style="dim"))
            log.write("")
        except Exception:
            pass

        self._update_observability()
        self._enable_input()
        self._update_status_indicator()
        self._update_session_indicator()
        self._refresh_landing_sessions()

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
            log = self.query_one("#conversation", RichLog)
            log.write("")
            log.write(Text("▎ task cancelled", style="yellow"))
            log.write("")
        except Exception:
            pass

        self._enable_input()
        self._update_status_indicator()

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _tool_detail(arguments: dict[str, Any] | None) -> str:
        if not arguments:
            return ""
        for key in ("path", "file_path", "filename", "query", "pattern", "command"):
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
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
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

    def _reset_observability(self) -> None:
        self.observability_model = getattr(
            getattr(self._agent, "llm", None),
            "model",
            self.observability_model or "Jimmy",
        )
        self.observability_turns = 0
        self.observability_tools = 0
        self.observability_input_tokens = 0
        self.observability_output_tokens = 0
        self.observability_total_tokens = 0
        self.observability_cost = 0.0
        self._update_observability()

    def _update_observability(self) -> None:
        try:
            widget = self.query_one("#observability", Static)

            has_usage = bool(
                self.observability_input_tokens
                or self.observability_output_tokens
                or self.observability_total_tokens
                or self.observability_cost > 0
            )
            has_run = bool(
                self.running
                or self.observability_turns
                or self.observability_tools
                or self._last_error
            )

            # Keep old/empty chats clean.
            if not has_run:
                widget.update("")
                return

            text = Text()
            text.append("⚡ ", style="bold #22d3ee")
            text.append(
                self.observability_model or "Jimmy",
                style="bold white",
            )
            text.append(
                f"  ·  {self.observability_turns} turns",
                style="dim #94a3b8",
            )
            text.append(
                f"  ·  {self.observability_tools} tools",
                style="dim #94a3b8",
            )
            text.append(
                f"  ·  {self._fmt_dur(self.elapsed)}",
                style="dim #94a3b8",
            )

            if has_usage:
                text.append("\n🪙 ", style="#fbbf24")
                if self.observability_input_tokens:
                    text.append(
                        f"{self._format_tokens(self.observability_input_tokens)} in",
                        style="dim #94a3b8",
                    )
                if self.observability_output_tokens:
                    if self.observability_input_tokens:
                        text.append("  ·  ", style="dim #475569")
                    text.append(
                        f"{self._format_tokens(self.observability_output_tokens)} out",
                        style="dim #94a3b8",
                    )
                if self.observability_total_tokens:
                    if self.observability_input_tokens or self.observability_output_tokens:
                        text.append("  ·  ", style="dim #475569")
                    text.append(
                        f"{self._format_tokens(self.observability_total_tokens)} total",
                        style="bold white",
                    )
                if self.observability_cost > 0:
                    text.append(
                        f"  ·  ${self.observability_cost:.2f}",
                        style="dim #94a3b8",
                    )

            if self._last_error:
                text.append(
                    f"\n✗ {self._last_error.splitlines()[0][:100]}",
                    style="bold red",
                )

            widget.update(text)
        except Exception:
            pass

    @staticmethod
    def _format_tokens(tokens: int) -> str:
        if tokens >= 1_000_000:
            return f"{tokens / 1_000_000:.1f}M"

        if tokens >= 1_000:
            return f"{tokens / 1_000:.1f}k"

        return str(tokens)


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
