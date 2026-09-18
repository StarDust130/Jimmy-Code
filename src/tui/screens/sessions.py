"""📚 Sessions — browse · resume · rename · delete · auto-clean.

Newest first.  Every row shows title · model · age · message count;
the ACTIVE session carries a green ● current badge.  Deletion is a
two-press confirmation (d, then d again — esc cancels); the auto-clean
policy cycles 15d → 30d → 90d → Never with `c` and applies immediately.

Storage lives in jimmy.sessions (SQLite); this screen is presentation
only — like the palette and model wizard it re-reads state on every
refresh and never caches it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, ClassVar

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from jimmy.sessions import CLEANUP_CHOICES, SessionRow

from ..kit.helpers import jimmy, keycap, short_model
from ..kit.theme import THEME

_PREVIEW_WIDTH = 38


def _ago(iso: str) -> str:
    try:
        then = datetime.fromisoformat(iso)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        seconds = int((datetime.now(timezone.utc) - then).total_seconds())
    except Exception:
        return "?"
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class RenameScreen(ModalScreen):
    """✏️ Inline rename card — enter saves · esc cancels."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    def __init__(self, current: str, on_save: Callable[[str], None]) -> None:
        super().__init__(id="rename-screen")
        self._current = current
        self._on_save = on_save

    def compose(self) -> Any:
        with Vertical(id="rename-card"):
            with Horizontal(id="rename-head"):
                yield Static(
                    Text.from_markup(f"[{THEME['accent']}]✏️[/] [#e2e6f2]Rename session[/]"),
                    id="rename-title",
                )
                yield Static(Text.from_markup(keycap("esc", "cancel")), id="rename-esc")
            yield Input(value=self._current, id="rename-input", placeholder="session title")

    def on_mount(self) -> None:
        try:
            inp = self.query_one("#rename-input", Input)
            inp.focus()
            # ✂️ pre-select the old title so typing REPLACES it — the
            #    behavior of every native rename dialog.  Falls back to
            #    end-of-text cursor on Textual versions without select_all.
            select_all = getattr(inp, "select_all", None)
            if callable(select_all):
                select_all()
            else:
                inp.cursor_position = len(inp.value)
        except Exception:
            pass

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        value = event.value.strip()
        if value and value != self._current:
            self._on_save(value)
        self.dismiss()

    def action_cancel(self) -> None:
        self.dismiss()


class SessionsScreen(ModalScreen):
    """📚 All saved sessions — newest first, live management."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "sessions_escape", "Close", priority=True),
        Binding("up", "session_up", show=False, priority=True),
        Binding("down", "session_down", show=False, priority=True),
        Binding("enter", "session_resume", show=False, priority=True),
        Binding("n", "session_new", show=False, priority=True),
        Binding("r", "session_rename", show=False, priority=True),
        Binding("d", "session_delete", show=False, priority=True),
        Binding("c", "session_cleanup", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__(id="sessions-screen")
        self._rows: list[Static] = []
        self._sessions: list[SessionRow] = []
        self._index = 0
        self._confirm_id: str | None = None

    # layout ──────────────────────────────────────────────────────────

    def compose(self) -> Any:
        with Vertical(id="sessions-card"):
            with Horizontal(id="sessions-head"):
                yield Static(
                    Text.from_markup(
                        f"[{THEME['accent']}]📚[/] [#e2e6f2]Sessions[/]"
                        f"  [#2a3148]·[/] [#7b8296]newest first[/]"
                    ),
                    id="sessions-title",
                )
                yield Static(Text.from_markup(keycap("esc", "close")), id="sessions-esc")
                yield Static("✕", id="sessions-close")
            yield Vertical(id="sessions-list")
            yield Static("", id="sessions-foot")

    def on_mount(self) -> None:
        try:
            self.set_focus(None)
        except Exception:
            pass
        self._run_cleanup()
        self._refresh()

    # data ────────────────────────────────────────────────────────────

    def _store(self):
        return jimmy(self).store

    def _run_cleanup(self) -> None:
        try:
            self._store().cleanup(self._store().cleanup_days())
        except Exception:
            pass

    def _refresh(self) -> None:
        try:
            self._sessions = list(self._store().list_sessions(limit=100))
        except Exception:
            self._sessions = []
        if self._index >= len(self._sessions):
            self._index = max(0, len(self._sessions) - 1)
        self._paint()

    def _paint(self) -> None:
        lst = self.query_one("#sessions-list", Vertical)
        lst.remove_children()
        self._rows = []
        if not self._sessions:
            lst.mount(
                Static(
                    Text.from_markup(
                        "[#565d73]no sessions yet — Jimmy saves each chat automatically[/]"
                    ),
                    classes="session-row",
                )
            )
        for i, row in enumerate(self._sessions):
            widget = Static(self._row_markup(row, i == self._index), classes="session-row")
            widget.tooltip = f"{row.workspace}\ncreated {_ago(row.created_at)}"
            self._rows.append(widget)
            lst.mount(widget)
        self._paint_foot()

    def _row_markup(self, row: SessionRow, selected: bool) -> Text:
        accent = THEME["accent"]
        active = row.id == getattr(jimmy(self), "_session_id", None)
        marker = f"[{accent}]›[/]" if selected else "[#3a4157]›[/]"
        badge = "  [#34d399]● current[/]" if active else ""
        title_style = "bold #f5f6fc" if selected else "#dbe0ee"
        meta = (
            f"{escape(short_model(row.model)) if row.model else '—'} · "
            f"{_ago(row.updated_at)} · {row.message_count} msgs"
        )
        return Text.from_markup(
            f"{marker}  [{title_style}]{escape(_clip(row.title, _PREVIEW_WIDTH))}[/]"
            f"{badge}   [#565d73]{meta}[/]"
        )

    def _paint_foot(self) -> None:
        foot = self.query_one("#sessions-foot", Static)
        try:
            policy = self._store().get_setting("cleanup_days") or "30"
        except Exception:
            policy = "30"
        if self._confirm_id is not None:
            foot.update(Text.from_markup("[#fb7185]⚠ press d again to delete — esc cancels[/]"))
        else:
            foot.update(
                Text.from_markup(
                    f"↵ resume · r rename · d delete · n new · "
                    f"[#f5c451]c auto-clean: {policy}[/] · esc close"
                )
            )

    def _current(self) -> SessionRow | None:
        if 0 <= self._index < len(self._sessions):
            return self._sessions[self._index]
        return None

    # ⌨️ keyboard (bulletproof path — mirrors the palette) ─────────────

    def on_key(self, event: events.Key) -> None:
        key = event.key
        if key == "escape":
            event.stop()
            event.prevent_default()
            self.action_sessions_escape()
        elif key == "up":
            event.stop()
            event.prevent_default()
            self.action_session_up()
        elif key == "down":
            event.stop()
            event.prevent_default()
            self.action_session_down()
        elif key == "enter":
            event.stop()
            event.prevent_default()
            self.action_session_resume()
        elif key == "n":
            event.stop()
            event.prevent_default()
            self.action_session_new()
        elif key == "r":
            event.stop()
            event.prevent_default()
            self.action_session_rename()
        elif key == "d":
            event.stop()
            event.prevent_default()
            self.action_session_delete()
        elif key == "c":
            event.stop()
            event.prevent_default()
            self.action_session_cleanup()

    # actions ─────────────────────────────────────────────────────────

    def action_sessions_escape(self) -> None:
        if self._confirm_id is not None:
            self._confirm_id = None
            self._paint_foot()
            return
        self.dismiss()

    def action_session_up(self) -> None:
        if not self._sessions:
            return
        self._index = (self._index - 1) % len(self._sessions)
        self._confirm_id = None
        self._paint()

    def action_session_down(self) -> None:
        if not self._sessions:
            return
        self._index = (self._index + 1) % len(self._sessions)
        self._confirm_id = None
        self._paint()

    def action_session_resume(self) -> None:
        row = self._current()
        if row is None:
            return
        app = jimmy(self)
        self.dismiss()
        app.open_session(row.id)

    def action_session_new(self) -> None:
        app = jimmy(self)
        self.dismiss()
        app.start_new_session()

    def action_session_rename(self) -> None:
        row = self._current()
        if row is None:
            return

        def _save(new_title: str) -> None:
            try:
                self._store().rename_session(row.id, new_title, source="user")
                self.notify("✏️ renamed", timeout=1.2)
            except Exception:
                self.notify("rename failed", severity="error", timeout=1.5)
            self._refresh()

        # 🪟 push via the APP — Screen.push_screen isn't available on
        #    every Textual version; App.push_screen is canonical.
        jimmy(self).push_screen(RenameScreen(row.title, _save))

    def action_session_delete(self) -> None:
        row = self._current()
        if row is None:
            return
        if self._confirm_id != row.id:
            self._confirm_id = row.id  # ⚠️ first press arms the confirmation
            self._paint_foot()
            return
        self._confirm_id = None
        try:
            self._store().delete_session(row.id)
            jimmy(self).forget_session(row.id)
            self.notify("🗑 session deleted", timeout=1.4)
        except Exception:
            self.notify("delete failed", severity="error", timeout=1.5)
        self._refresh()

    def action_session_cleanup(self) -> None:
        store = self._store()
        try:
            current = store.get_setting("cleanup_days") or "30"
            if current in CLEANUP_CHOICES:
                nxt = CLEANUP_CHOICES[(CLEANUP_CHOICES.index(current) + 1) % len(CLEANUP_CHOICES)]
            else:
                nxt = "30"
            store.set_cleanup_days(nxt)
            removed = store.cleanup(store.cleanup_days())
            self._refresh()
            msg = f"🧹 auto-clean: {nxt}"
            if removed:
                msg += f" · removed {removed} old session{'s' if removed != 1 else ''}"
            self.notify(msg, timeout=1.8)
        except Exception:
            self.notify("could not change cleanup policy", severity="error", timeout=1.5)

    # 🖱️ mouse ────────────────────────────────────────────────────────

    def on_click(self, event: events.Click) -> None:
        control = event.control
        if control is None:
            return
        if getattr(control, "id", None) == "sessions-close":
            event.stop()
            self.dismiss()
            return
        for i, widget in enumerate(self._rows):
            if control is widget:
                event.stop()
                self._index = i
                self._confirm_id = None
                self._paint()
                self.action_session_resume()
                return
        node: Any = control
        while node is not None:
            if getattr(node, "id", None) == "sessions-card":
                return
            node = getattr(node, "parent", None)
        self.dismiss()
