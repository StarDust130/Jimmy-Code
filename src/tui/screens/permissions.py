"""🛡️ Permission UI — mode picker + approval prompt.

Both screens are thin: ALL policy lives in ``jimmy.permissions``; these
screens only display state and collect the user's decision, then call
back into JimmyApp (which owns the agent).

PermissionScreen — three color-coded mode CARDS (not a boring list):
each shows the emoji + name, a 1·2·3 hotkey, the one-line description,
and a capability strip telling you exactly what runs automatically (✓)
and what asks first (✋).  Apply via ↑↓ + ↵, the hotkeys, or a click —
the change is instant and announced (never silent).

ApprovalScreen is FAIL-CLOSED: every exit path that isn't an explicit
allow (esc · ✕ · click outside) resolves as DENY — the agent must never
hang and nothing may ever run unapproved.
"""

from __future__ import annotations

from typing import Any, ClassVar

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from jimmy.permissions import MODE_META, Decision, PermissionMode

from ..kit.helpers import jimmy, keycap, tool_display
from ..kit.theme import THEME

_MODE_ORDER: tuple[PermissionMode, ...] = (
    PermissionMode.ASK,
    PermissionMode.AUTO,
    PermissionMode.FULL,
)

# 🎨 per-mode identity — color · hotkey · capability strip
#    ✓ = runs automatically        ✋ = asks you first
_MODE_STYLE: dict[PermissionMode, tuple[str, str, str]] = {
    PermissionMode.ASK: (
        "#34d399",
        "1",
        "[#34d399]📖 read ✓[/]  [#2a3148]·[/]  [#fbbf24]✎ edit ✋[/]  "
        "[#2a3148]·[/]  [#fbbf24]🧪 tests ✋[/]  [#2a3148]·[/]  "
        "[#fbbf24]💻 shell ✋[/]  [#2a3148]·[/]  [#fbbf24]🌿 git ✋[/]",
    ),
    PermissionMode.AUTO: (
        "#fbbf24",
        "2",
        "[#34d399]📖 read ✓[/]  [#2a3148]·[/]  [#34d399]✎ edit ✓[/]  "
        "[#2a3148]·[/]  [#34d399]🧪 tests ✓[/]  [#2a3148]·[/]  "
        "[#fbbf24]💻 shell ✋[/]  [#2a3148]·[/]  [#fbbf24]🌿 git push ✋[/]",
    ),
    PermissionMode.FULL: (
        "#fb7185",
        "3",
        "[#34d399]⚡ everything runs — no prompts, full speed[/]",
    ),
}


class PermissionScreen(ModalScreen):
    """🛡️ Pick the permission mode — applies immediately, never silent."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close_perm", "Close", priority=True),
        Binding("up", "perm_up", show=False, priority=True),
        Binding("down", "perm_down", show=False, priority=True),
        Binding("enter", "perm_apply", show=False, priority=True),
        Binding("1", "perm_one", show=False, priority=True),
        Binding("2", "perm_two", show=False, priority=True),
        Binding("3", "perm_three", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__(id="permission-screen")
        self._rows: list[Static] = []
        self._index = 0

    # layout ──────────────────────────────────────────────────────────

    def compose(self) -> Any:
        with Vertical(id="perm-card"):
            with Horizontal(id="perm-head"):
                yield Static(
                    Text.from_markup(
                        f"[{THEME['accent']}]🛡️[/] [#e2e6f2]Permissions[/]"
                        f"  [#2a3148]·[/] [#7b8296]how Jimmy acts on your project[/]"
                    ),
                    id="perm-title",
                )
                yield Static(Text.from_markup(keycap("esc", "close")), id="perm-esc")
                yield Static("✕", id="perm-close")

            yield Static(
                Text.from_markup(
                    "[#34d399]✓[/] [#8a91a8]runs automatically[/]   "
                    "[#fbbf24]✋[/] [#8a91a8]asks you first[/]"
                ),
                id="perm-legend",
            )

            yield Vertical(id="perm-list")

            yield Static(
                "↑↓ navigate · ↵ or 1·2·3 apply · click a card · change is instant",
                id="perm-foot",
            )

    def on_mount(self) -> None:
        try:
            current = jimmy(self).current_permission_mode()
            if current in _MODE_ORDER:
                self._index = _MODE_ORDER.index(current)
        except Exception:
            pass

        lst = self.query_one("#perm-list", Vertical)
        for mode in _MODE_ORDER:
            row = Static("", classes="perm-row")
            row.tooltip = f"switch to {MODE_META[mode][1]}"
            self._rows.append(row)
            lst.mount(row)

        self._paint()

    # painting ────────────────────────────────────────────────────────

    def _paint(self) -> None:
        try:
            current = jimmy(self).current_permission_mode()
        except Exception:
            current = None

        for i, (mode, row) in enumerate(zip(_MODE_ORDER, self._rows)):
            selected = i == self._index
            row.update(self._row_markup(mode, current, selected))
            if selected:
                row.add_class("selected")
            else:
                row.remove_class("selected")

    def _row_markup(
        self,
        mode: PermissionMode,
        current: PermissionMode | None,
        selected: bool,
    ) -> Text:
        """One mode card — 3 lines: title+hotkey · description · caps."""
        color, hotkey, caps = _MODE_STYLE[mode]
        emoji, name, desc = MODE_META[mode]
        accent = THEME["accent"]

        marker = f"[{accent}]▸[/]" if selected else "[#3a4157]▸[/]"
        badge = "  [#34d399]● active[/]" if mode is current else ""
        name_style = "bold #f5f6fc" if selected else f"bold {color}"

        line1 = (
            f"{marker}  [{color}]{emoji}[/]  "
            f"[{name_style}]{escape(name)}[/]{badge}   {keycap(hotkey, '')}"
        )
        line2 = f"    [#aab2c7]{escape(desc)}[/]"
        line3 = f"    {caps}"

        return Text.from_markup("\n".join((line1, line2, line3)))

    # navigation ──────────────────────────────────────────────────────

    def action_perm_up(self) -> None:
        self._index = (self._index - 1) % len(_MODE_ORDER)
        self._paint()

    def action_perm_down(self) -> None:
        self._index = (self._index + 1) % len(_MODE_ORDER)
        self._paint()

    def action_perm_apply(self) -> None:
        self._apply_mode(_MODE_ORDER[self._index])

    def action_perm_one(self) -> None:
        self._apply_mode(_MODE_ORDER[0])

    def action_perm_two(self) -> None:
        self._apply_mode(_MODE_ORDER[1])

    def action_perm_three(self) -> None:
        self._apply_mode(_MODE_ORDER[2])

    def action_close_perm(self) -> None:
        self.dismiss()

    def _apply_mode(self, mode: PermissionMode) -> None:
        jimmy(self).set_permission_mode(mode)  # 🔔 notifies — never silent
        self.dismiss()

    # mouse ───────────────────────────────────────────────────────────

    def on_click(self, event: events.Click) -> None:
        control = event.control
        if control is None:
            return

        if getattr(control, "id", None) == "perm-close":
            event.stop()
            self.dismiss()
            return

        for i, row in enumerate(self._rows):
            if control is row:
                event.stop()
                self._apply_mode(_MODE_ORDER[i])
                return

        # click outside the card → close
        node: Any = control
        while node is not None:
            if getattr(node, "id", None) == "perm-card":
                return
            node = getattr(node, "parent", None)
        self.dismiss()


class ApprovalScreen(ModalScreen):
    """🛡️ One pending action — Allow · Allow for session · Deny · Full.

    esc always means DENY (safe default); the agent never hangs.
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "deny", "Deny", priority=True),
        Binding("enter", "allow", "Allow", priority=True),
        Binding("s", "session", "Allow for session", priority=True),
        Binding("f", "full_access", "Full access", priority=True),
    ]

    def __init__(self, request: dict[str, Any]) -> None:
        super().__init__(id="approval-screen")
        self._request = dict(request)
        self._request_id = str(request.get("id", ""))
        self._tool_name = str(request.get("tool", ""))
        self._resolved = False

    # layout ──────────────────────────────────────────────────────────

    def compose(self) -> Any:
        icon, action, detail = tool_display(self._tool_name, self._request.get("arguments") or {})
        # 🧹 "Git git" reads silly — drop detail when it repeats the action.
        if detail and detail.strip().lower() == action.strip().lower():
            detail = ""

        summary = str(self._request.get("summary", "")).strip()
        reason = str(self._request.get("reason", "")).strip()

        with Vertical(id="approval-card"):
            with Horizontal(id="approval-head"):
                yield Static(
                    Text.from_markup("[#fbbf24]🛡️[/] [#e2e6f2]Approval required[/]"),
                    id="approval-title",
                )
                yield Static(Text.from_markup(keycap("esc", "deny")), id="approval-esc")
                yield Static("✕", id="approval-close")

            if detail:
                yield Static(
                    Text.from_markup(
                        f"[#aab2c7]{icon}[/] [bold #f5f6fc]{escape(action)}[/]"
                        f"  [#7b8296]{escape(detail)}[/]"
                    ),
                    classes="approval-row",
                )
            else:
                yield Static(
                    Text.from_markup(f"[#aab2c7]{icon}[/] [bold #f5f6fc]{escape(action)}[/]"),
                    classes="approval-row",
                )

            if summary:
                yield Static(
                    Text.from_markup(f"[#565d73]Jimmy wants to:[/] [#dbe0ee]{escape(summary)}[/]"),
                    classes="approval-row",
                )

            if reason:
                yield Static(
                    Text.from_markup(f"[#f5c451]why:[/] [#8a91a8]{escape(reason)}[/]"),
                    classes="approval-row",
                )

            with Horizontal(id="approval-actions"):
                yield Static("✅ Allow", id="btn-allow", classes="perm-btn")
                yield Static("🔓 Allow session", id="btn-session", classes="perm-btn")
                yield Static("❌ Deny", id="btn-deny", classes="perm-btn")

            yield Static(
                "🔓 Switch to Full Access — everything runs without asking",
                id="btn-full",
            )

            yield Static(
                "↵ allow · s this session · f full access · esc deny",
                id="approval-foot",
            )

    def on_mount(self) -> None:
        if not self._request_id:
            # malformed request → fail closed
            self.call_after_refresh(self.action_deny)

    # decisions ───────────────────────────────────────────────────────

    def action_allow(self) -> None:
        self._finish(Decision.ALLOW)

    def action_session(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        app = jimmy(self)
        app.approve_for_session(self._request_id, self._tool_name)
        self.dismiss()

    def action_full_access(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        app = jimmy(self)
        app.set_permission_mode(PermissionMode.FULL)  # 🔔 notifies
        app.resolve_approval(self._request_id, Decision.ALLOW)
        self.dismiss()

    def action_deny(self) -> None:
        self._finish(Decision.DENY)

    def _finish(self, decision: Decision) -> None:
        if self._resolved:
            return
        self._resolved = True
        jimmy(self).resolve_approval(self._request_id, decision)
        self.dismiss()

    # mouse ───────────────────────────────────────────────────────────

    def on_click(self, event: events.Click) -> None:
        control = event.control
        if control is None:
            return

        cid = getattr(control, "id", None)
        if cid == "btn-allow":
            event.stop()
            self.action_allow()
            return
        if cid == "btn-session":
            event.stop()
            self.action_session()
            return
        if cid in ("btn-deny", "approval-close"):
            event.stop()
            self.action_deny()
            return
        if cid == "btn-full":
            event.stop()
            self.action_full_access()
            return

        # click outside the card → deny (fail closed)
        node: Any = control
        while node is not None:
            if getattr(node, "id", None) == "approval-card":
                return
            node = getattr(node, "parent", None)
        self.action_deny()
