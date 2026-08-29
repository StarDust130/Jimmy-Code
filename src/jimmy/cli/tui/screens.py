from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Static

from jimmy.permissions.manager import PermissionMode

from .constants import HELP_TEXT


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
                    with Horizontal(classes="session-row"):
                        yield SessionCard(session, classes="all-session-card")
                        yield DeleteButton(session.get("id", ""))
            footer_text = Text()
            footer_text.append("↑↓ select · Enter open · ", style="dim")
            footer_text.append("Esc", style="red")
            footer_text.append(" close", style="dim")
            yield Static(footer_text, id="all-sessions-footer")

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

    def on_delete_button_pressed(self, event: DeleteButton.Pressed) -> None:
        session_id = event.session_id

        def handle_confirm(confirmed: bool | None) -> None:
            if confirmed:
                self._delete_session(session_id)

        self.app.push_screen(DeleteConfirmScreen(), handle_confirm)

    def _delete_session(self, session_id: str) -> None:
        # Call app's deletion method (handles storage & notification)
        app = cast(Any, self.app)
        app._delete_session(session_id)

        # Remove from local list
        self.sessions = [s for s in self.sessions if s.get("id") != session_id]

        # Refresh the UI immediately
        self._refresh_list()

        # If no sessions left, close the dialog
        if not self.sessions:
            self.dismiss(None)
        else:
            # Ensure the screen is properly refreshed
            self.refresh()

    def _refresh_list(self) -> None:
        """Rebuild the session list widget."""
        list_container = self.query_one("#all-sessions-list", Vertical)
        # Clear all existing children
        list_container.remove_children()

        # Re-add each session row
        for session in self.sessions:
            row = Horizontal(classes="session-row")
            card = SessionCard(session, classes="all-session-card")
            delete_btn = DeleteButton(session.get("id", ""))
            row.mount(card, delete_btn)
            list_container.mount(row)

        # Reapply selection
        if self.sessions:
            self.selected_index = min(self.selected_index, len(self.sessions) - 1)
            self._update_selection()
        else:
            # No sessions – nothing to select
            pass


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
        footer_text = Text()
        footer_text.append("↑↓ select · Enter confirm · ", style="dim")
        footer_text.append("Esc", style="red")
        footer_text.append(" close", style="dim")

        yield Center(
            Vertical(
                Static("🔐  Permission Mode", id="permission-title"),
                Static(
                    "Choose how Jimmy should handle tool permissions.",
                    id="permission-subtitle",
                ),
                Static("", id="permission-options"),
                Static(footer_text, id="permission-footer"),
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
        footer_text = Text()
        footer_text.append("Y Allow · N Deny · F Full Access · ", style="dim")
        footer_text.append("Esc", style="red")
        footer_text.append(" to deny", style="dim")

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
                Static(footer_text, id="approval-footer"),
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
