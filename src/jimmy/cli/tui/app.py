from __future__ import annotations

import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, cast

from rich.markdown import Markdown
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Footer, Input, RichLog, Static

from jimmy.agent.events import AgentEvent
from jimmy.permissions.manager import PermissionMode

from .constants import LOGO, SPINNER_FRAMES, THINKING_BAR, TOOL_ICONS
from .screens import (
    AllSessionsScreen,
    DeleteButton,
    DeleteConfirmScreen,
    HelpScreen,
    PermissionPrompt,
    PermissionScreen,
    SessionCard,
    ViewAllLink,
)


class JimmyFooter(Footer):
    """Custom footer: hides Ctrl+N on landing, colours Esc in red."""

    def get_bindings(self) -> list[Binding]:
        app = cast(JimmyTUI, self.app)
        if app.mode == "landing":
            return [b for b in Footer.get_bindings(self) if b.action != "new_task"]
        return Footer.get_bindings(self)

    def _make_key_text(self, binding: Binding) -> Text:
        text = Footer._make_key_text(self, binding)
        if binding.key in ("escape", "esc"):
            parts = text.split(" ")
            if parts:
                parts[0] = Text(parts[0].plain, style="red")
                text = Text(" ").join(parts)
        return text


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
        self._permission_waiting = False
        self._task_generation = 0
        self._current_generation = 0

        self._last_response: str = ""
        self._conversation_history: list[dict[str, str]] = []
        self._full_transcript: list[dict[str, str]] = []
        self._files_touched: set[str] = set()

        self._stream_buffer = ""
        self._streaming = False

        self._accent_idx = 0
        self._typewriter_idx = 0
        self._typewriter_timer: Any = None
        self._think_idx = 0

        self._git_branch = self._detect_git_branch()

        self.current_session_id: str | None = None
        self._current_task: str | None = None
        self._agent_header_needed = False

        self._prompt_history: list[str] = []
        self._history_pos: int = -1
        self._history_draft: str = ""

    def compose(self) -> ComposeResult:
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
                ViewAllLink(),
                id="recent-sessions-wrapper",
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
            Static("", id="streaming-response"),
            Static("", id="observability"),
            Static("", id="typing-indicator"),
            Horizontal(
                Button(
                    "⧉ Copy",
                    id="copy-conversation",
                    variant="default",
                ),
                id="chat-actions",
            ),
            Input(
                placeholder="Ask Jimmy anything...",
                id="prompt-chat",
            ),
            id="chat-main",
        )

        yield JimmyFooter()

    def on_mount(self) -> None:
        self._apply_mode(self.mode)
        self._update_brand()
        self._update_project()
        self._update_permission_mode()
        self._update_session_indicator()
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "copy-conversation":
            self.action_copy_conversation()

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
        if not self._full_transcript:
            self._notify("No conversation to copy", "warning")
            return
        lines: list[str] = []
        for msg in self._full_transcript:
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"YOU:\n{content}")
            elif role == "assistant":
                lines.append(f"JIMMY:\n{content}")
            elif role == "tool_start":
                lines.append(f"TOOL: {content}")
            elif role == "tool_end":
                lines.append(f"   {content}")
            lines.append("")
        text = "\n".join(lines).strip()
        if text:
            self._copy_text(text, "Conversation copied")
        else:
            self._notify("No conversation to copy", "warning")

    def _copy_text(self, text: str, success_msg: str) -> None:
        if not text:
            self._notify("Nothing to copy", "warning")
            return

        # Try pyperclip first if available
        try:
            import pyperclip

            pyperclip.copy(text)
            self._notify(success_msg, "information")
            return
        except Exception:
            pass

        # Fallback to platform-specific commands
        import platform

        system = platform.system()
        try:
            if system == "Windows":
                subprocess.run(["clip"], input=text, text=True, check=True, timeout=2)
            elif system == "Darwin":
                subprocess.run(["pbcopy"], input=text, text=True, check=True, timeout=2)
            else:
                # Try wl-copy (Wayland) then xclip (X11)
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
            # Final fallback: print to console for manual copy
            self._notify(
                "Copy failed — text printed to console for manual copy.",
                "warning",
            )
            print(text)

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
            if not self._permission_waiting:
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
            try:
                if self._permission_waiting:
                    self.query_one(
                        "#typing-indicator",
                        Static,
                    ).update(
                        Text(
                            "🔐  Waiting for permission",
                            style="bold #fbbf24",
                        )
                    )
                else:
                    bar = THINKING_BAR[self._think_idx]
                    label = "Jimmy is responding" if self._streaming else "Jimmy is thinking"
                    self.query_one(
                        "#typing-indicator",
                        Static,
                    ).update(
                        Text(
                            f"{bar}  {label}",
                            style="dim #22d3ee",
                        )
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
            if self.current_session_id and self._current_task:
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
        try:
            self.query_one(JimmyFooter).refresh()
        except Exception:
            pass

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
        self.current_session_id = None
        if hasattr(self._agent, "current_session_id"):
            self._agent.current_session_id = None
        self._current_task = None
        self._history_pos = -1
        self._history_draft = ""
        self._update_status_indicator()
        self._update_session_indicator()
        self._start_typewriter()
        self._focus_input()

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
            if self._permission_waiting:
                text.append("🔐 ", style="bold #fbbf24")
                text.append(
                    "waiting for approval",
                    style="bold #fbbf24",
                )
            else:
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

    def _get_sessions(self, clean_old: bool = True) -> list[dict]:
        store = getattr(self._agent, "session_store", None)
        if store is None:
            return []
        try:
            all_sessions = store.list()
        except Exception:
            return []

        if not clean_old:
            return all_sessions

        now = datetime.now(UTC)
        cutoff = now - timedelta(days=15)
        kept = []
        for sess in all_sessions:
            updated_at_str = sess.get("updated_at", "")
            try:
                dt = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                if dt < cutoff:
                    store.delete(sess.get("id", ""))
                    continue
            except Exception:
                pass
            kept.append(sess)
        return kept

    def _show_all_sessions(self) -> None:
        sessions = self._get_sessions(clean_old=True)
        if not sessions:
            self._notify("No sessions found", "warning")
            return

        def handle_selection(result: str | None) -> None:
            if result:
                self._resume_session(result)

        self.push_screen(
            AllSessionsScreen(sessions, self.current_session_id),
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

        self.current_session_id = session_id
        if hasattr(self._agent, "current_session_id"):
            self._agent.current_session_id = session_id
        self._current_task = getattr(state, "task", "Session")
        self._conversation_history = []
        self._full_transcript = []
        self._files_touched = set()
        self._last_response = ""
        self._step_number = 0
        self.turn = getattr(state, "turn_count", 0)
        self._stream_buffer = ""
        self._streaming = False

        self._clear_conversation()

        for msg in getattr(state, "messages", []):
            role = msg.get("role")

            if role == "user":
                content = str(msg.get("content", ""))
                self._conversation_history.append({"role": "user", "content": content})
                self._full_transcript.append({"role": "user", "content": content})
                self._render_user_message(content)

            elif role == "assistant":
                content = str(msg.get("content", ""))
                if not content.strip():
                    continue

                self._conversation_history.append({"role": "assistant", "content": content})
                self._full_transcript.append({"role": "assistant", "content": content})
                self._render_agent_header()
                self._render_content(content)

            elif role == "tool":
                self._render_history_tool(msg)
                self._full_transcript.append(
                    {
                        "role": "tool_start",
                        "content": f"{msg.get('name', 'tool')} {msg.get('content', '')}",
                    }
                )

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

    def _render_history_tool(self, message: dict[str, Any]) -> None:
        try:
            log = self.query_one("#conversation", RichLog)
            name = str(message.get("name", "tool"))
            content = str(message.get("content", "") or "")

            log.write(
                Text(
                    f"  ▪ {name}",
                    style="bold white",
                )
            )

            if content:
                first_line = content.splitlines()[0].strip()
                if first_line:
                    log.write(
                        Text(
                            f"    {first_line[:120]}",
                            style="dim",
                        )
                    )
        except Exception:
            pass

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
                self._notify("Session deleted", "information")
            else:
                self._notify("Failed to delete session", "error")
                return
        except Exception:
            self._notify("Failed to delete session", "error")
            return

        if self.current_session_id == session_id:
            if not isinstance(self.screen, AllSessionsScreen):
                self.action_new_task()
            else:
                self.current_session_id = None
                self._current_task = None
                if hasattr(self._agent, "current_session_id"):
                    self._agent.current_session_id = None
                self._update_session_indicator()
        else:
            self._update_session_indicator()

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
        self._permission_waiting = False
        self._stream_buffer = ""
        self._streaming = False
        self._agent_header_needed = True
        self._hide_streaming_response()
        self._task_generation += 1
        self._current_generation = self._task_generation

        if self._typewriter_timer:
            try:
                self._typewriter_timer.stop()
            except Exception:
                pass

        self._current_task = task
        self.mode = "chat"

        self._write_user_message(task)
        self._update_status_indicator()
        self._disable_input()

        if self.current_session_id is None:
            self._start_agent(task)
        else:
            self._start_agent_continue(task)

    # ------------------------------------------------------------------
    # CONVERSATION
    # ------------------------------------------------------------------

    def _write_user_message(self, message: str) -> None:
        self._conversation_history.append({"role": "user", "content": message})
        self._full_transcript.append({"role": "user", "content": message})
        self._render_user_message(message)

    def _write_agent_text(self, text: str) -> None:
        content = str(text or "")
        if not content.strip():
            return

        self._last_response = content
        self._conversation_history.append({"role": "assistant", "content": content})
        self._full_transcript.append({"role": "assistant", "content": content})
        self._ensure_agent_header()
        self._render_content(content)

    def _render_content(self, text: str | Text) -> None:
        try:
            log = self.query_one("#conversation", RichLog)
            markdown_text = text.plain if isinstance(text, Text) else text

            if not markdown_text.strip():
                return

            log.write(
                Markdown(
                    markdown_text,
                    code_theme="monokai",
                )
            )
        except Exception:
            try:
                log = self.query_one("#conversation", RichLog)
                markdown_text = text.plain if isinstance(text, Text) else text
                for line in markdown_text.splitlines():
                    log.write(Text(f"▎ {line}", style="#d8dee9"))
            except Exception:
                pass

    def _write_tool_start(
        self, tool_name: str | None, arguments: dict[str, Any] | None = None
    ) -> None:
        """Display the start of a tool call with name and a short target."""
        try:
            log = self.query_one("#conversation", RichLog)
            icon = TOOL_ICONS.get(tool_name or "", "▪")
            name = tool_name or "unknown"

            t = Text()
            t.append(f"  {icon} ", style="cyan")
            t.append(name, style="bold white")

            detail = self._tool_detail(arguments or {})
            if detail:
                t.append("  →  ", style="dim")
                t.append(detail, style="italic #94a3b8")

            log.write(t)
            self._full_transcript.append(
                {"role": "tool_start", "content": f"{name} → {detail}" if detail else name}
            )
        except Exception:
            pass

    def _write_tool_end(self, elapsed: float, success: bool, result_preview: str = "") -> None:
        """Display the end of a tool call with status and elapsed time."""
        try:
            log = self.query_one("#conversation", RichLog)
            t = Text()
            t.append("    ")
            t.append("✓ " if success else "× ", style=("green" if success else "red"))
            t.append(self._fmt_dur(elapsed), style="dim")
            if result_preview:
                t.append("  ", style="dim")
                t.append(result_preview[:80], style="italic #64748b")
            log.write(t)

            self._full_transcript.append(
                {
                    "role": "tool_end",
                    "content": f"{'✓' if success else '×'} {self._fmt_dur(elapsed)} {result_preview[:80]}",
                }
            )
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
        self._full_transcript.clear()
        self._last_response = ""
        self._files_touched.clear()
        self._agent_header_needed = False
        self._stream_buffer = ""
        self._streaming = False
        self._hide_streaming_response()

    # ------------------------------------------------------------------
    # AGENT WORKER
    # ------------------------------------------------------------------

    @work(thread=True, group="agent", exclusive=True, exit_on_error=False)
    def _start_agent(self, task: str) -> None:
        gen = self._current_generation

        try:
            self._agent.run(
                task,
                on_event=lambda event: self._agent_event(
                    event,
                    gen,
                ),
                on_permission=self._ask_permission,
                on_text_delta=lambda text: self._agent_text_delta(
                    text,
                    gen,
                ),
            )

            session_id = getattr(
                self._agent,
                "current_session_id",
                None,
            )

            if session_id:
                self.current_session_id = session_id

        except KeyboardInterrupt:
            if not self._worker_cancelled:
                self.call_from_thread(
                    self._agent_failed,
                    RuntimeError("Jimmy task cancelled."),
                    gen,
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

    @work(thread=True, group="agent", exclusive=True, exit_on_error=False)
    def _start_agent_continue(self, task: str) -> None:
        gen = self._current_generation
        session_id = self.current_session_id

        if not session_id:
            self.call_from_thread(
                self._agent_failed,
                RuntimeError("No active session to continue."),
                gen,
            )
            return

        try:
            self._agent.continue_session(
                session_id=session_id,
                task=task,
                on_event=lambda event: self._agent_event(
                    event,
                    gen,
                ),
                on_permission=self._ask_permission,
                on_text_delta=lambda text: self._agent_text_delta(
                    text,
                    gen,
                ),
            )
        except KeyboardInterrupt:
            if not self._worker_cancelled:
                self.call_from_thread(
                    self._agent_failed,
                    RuntimeError("Jimmy task cancelled."),
                    gen,
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

    @work(thread=True, group="agent", exclusive=True, exit_on_error=False)
    def _start_agent_resume(self, session_id: str) -> None:
        gen = self._current_generation

        try:
            self.current_session_id = session_id
            if hasattr(self._agent, "current_session_id"):
                self._agent.current_session_id = session_id

            self._agent.resume(
                session_id,
                on_event=lambda event: self._agent_event(
                    event,
                    gen,
                ),
                on_permission=self._ask_permission,
                on_text_delta=lambda text: self._agent_text_delta(
                    text,
                    gen,
                ),
            )
        except KeyboardInterrupt:
            if not self._worker_cancelled:
                self.call_from_thread(
                    self._agent_failed,
                    RuntimeError("Jimmy task cancelled."),
                    gen,
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

    def _agent_text_delta(
        self,
        text: str,
        generation: int,
    ) -> None:
        if not text:
            return

        self.call_from_thread(
            self._append_stream_text,
            text,
            generation,
        )

    def _append_stream_text(
        self,
        text: str,
        generation: int,
    ) -> None:
        if generation != self._current_generation:
            return

        if self._worker_cancelled:
            return

        self._streaming = True
        self._stream_buffer += text
        self.status = "responding"
        self._ensure_agent_header()

        try:
            widget = self.query_one(
                "#streaming-response",
                Static,
            )

            widget.styles.display = "block"
            widget.update(
                Text(
                    self._stream_buffer + "▌",
                    style="#d8dee9",
                )
            )

            self.query_one(
                "#conversation",
                RichLog,
            ).scroll_end()
        except Exception:
            pass

        self._update_status_indicator()

    def _hide_streaming_response(self) -> None:
        try:
            widget = self.query_one(
                "#streaming-response",
                Static,
            )
            widget.update("")
            widget.styles.display = "none"
        except Exception:
            pass

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

        self._permission_waiting = True
        self.status = "waiting"
        self._update_status_indicator()
        self.call_from_thread(show_prompt)

        try:
            finished.wait()
        finally:
            self._permission_waiting = False
            if self.running and self.status == "waiting":
                self.status = "running"
            self._update_status_indicator()

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
            self._ensure_agent_header()
            self.current_tool = event.tool_name or "unknown"

            detail = self._tool_detail(event.arguments)
            if detail:
                self.current_file = detail
                if "/" in detail or "\\" in detail or "." in Path(detail).name:
                    self._files_touched.add(detail)

            self.observability_tools += 1

            self._write_tool_start(event.tool_name, event.arguments)

        elif event.kind == "tool_end":
            self._step_number += 1

            success = event.message not in {
                "error",
                "denied",
            }

            self._write_tool_end(
                event.elapsed or 0.0,
                success,
                getattr(event, "message", "") or "",
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

        self._hide_streaming_response()
        self._stream_buffer = ""
        self._streaming = False
        self._agent_header_needed = True

        if result.strip():
            self._last_response = result.strip()
            self._conversation_history.append({"role": "assistant", "content": result.strip()})
            self._full_transcript.append({"role": "assistant", "content": result.strip()})

        try:
            log = self.query_one("#conversation", RichLog)
            log.write("")
            log.write(Text("▎ ✓ done", style="bold green"))
            log.write(Text(f"▎ {self._summary()}", style="dim"))
            if result.strip():
                log.write("")
                self._agent_header_needed = True
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
        self._hide_streaming_response()
        self._stream_buffer = ""
        self._streaming = False

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

    # ------------------------------------------------------------------
    # CANCEL
    # ------------------------------------------------------------------

    def action_cancel_task(self) -> None:
        if not self.running:
            return

        self._worker_cancelled = True
        self._permission_waiting = False
        self._hide_streaming_response()
        self._stream_buffer = ""
        self._streaming = False

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
