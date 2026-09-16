"""ctrl+p command palette — small, floating, centered, instant.

Close paths (all funnel to app.close_palette → canonical pop + focus
restore): esc (esc in a submenu goes BACK to commands first) · ✕ header ·
"✕ Close menu" command · click outside the card · ctrl+p again.
Theme view: ↑/↓ applies the theme LIVE as you move; ↵ returns to commands.

Rows are repainted from this class's own ``_entries`` model — widget
internals are never read — and every row's Text carries EXPLICIT colors
on every segment, so first-open can never be dark-on-dark.
"""

from __future__ import annotations

from typing import Any, Callable, ClassVar, cast

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from ..kit.helpers import jimmy, keycap
from ..kit.theme import THEME, THEME_ORDER, THEMES


class PaletteSearch(Input):
    """The palette's search box — esc / ↑ / ↓ intercepted on the widget
    itself, so no binding-resolution order can ever swallow them."""

    def on_key(self, event: events.Key) -> None:
        screen = self.screen
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            cast("CommandPaletteScreen", screen).palette_escape()
        elif event.key == "up":
            event.stop()
            event.prevent_default()
            cast("CommandPaletteScreen", screen).palette_move(-1)
        elif event.key == "down":
            event.stop()
            event.prevent_default()
            cast("CommandPaletteScreen", screen).palette_move(1)


class CommandPaletteScreen(ModalScreen):
    """Small premium floating command menu — never fullscreen, never slow.

    Views: ``commands`` (root) · ``shortcuts`` (keycaps) · ``themes``
    (↑↓ applies live, each dot shows that theme's own color).
    """

    BINDINGS: ClassVar[list] = [
        Binding("escape", "palette_escape_action", "Close", priority=True),
    ]

    SHORTCUT_ROWS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("↵", "send · begin"),
        ("↑ ↓", "prompt history"),
        ("esc", "interrupt jimmy / go back in menus"),
        ("ctrl+n", "home — esc exits home"),
        ("ctrl+p", "command menu (toggle)"),
        ("ctrl+c", "copy last prompt + reply"),
        ("ctrl+a", "copy whole chat"),
        ("ctrl+l", "clear the input line"),
        ("ctrl+s", "sound play / stop"),
        ("ctrl+q", "quit"),
        ("drag", "mouse-select text to copy"),
        ("/", "clear · home · sound · copy · copyall · quit"),
    )

    def __init__(self) -> None:
        super().__init__(id="palette-screen")
        self._mode = "commands"  # commands | shortcuts | themes
        self._index = 0
        self._entries: list[dict[str, Any]] = []
        self._search: PaletteSearch | None = None
        self._list: Vertical | None = None
        self._section: Static | None = None
        self._title: Static | None = None

    def compose(self) -> Any:
        with Vertical(id="palette"):
            with Horizontal(id="palette-head"):
                yield Static("", id="palette-title")
                yield Static(Text.from_markup(keycap("esc", "close")), id="palette-esc")
                yield Static("✕", id="palette-close")
            yield PaletteSearch(placeholder="🔍  Search commands…", id="palette-search")
            yield Static("Suggested", id="palette-section")
            yield Vertical(id="palette-list")
            yield Static(
                "↑↓ navigate · ↵ select · esc back/close · click outside closes", id="palette-foot"
            )

    def on_mount(self) -> None:
        self._title = self.query_one("#palette-title", Static)
        self._search = self.query_one("#palette-search", PaletteSearch)
        self._list = self.query_one("#palette-list", Vertical)
        self._section = self.query_one("#palette-section", Static)
        self._paint_title()
        self._rebuild("")

        def _open() -> None:
            self._paint_selection()  # repaint once arranged — never dark
            if self._search is not None:
                self._search.focus()

        self.call_after_refresh(_open)

    # chrome ─────────────────────────────────────────────────────────────

    def _paint_title(self) -> None:
        if self._title is not None:
            self._title.update(Text.from_markup(f"[{THEME['accent']}]✦[/] [#e2e6f2]Commands[/]"))

    # row model ──────────────────────────────────────────────────────────

    def _commands(self) -> list[tuple[str, str, Callable[[], None]]]:
        """ALL commands live here (the root list)."""
        app = jimmy(self)
        return [
            ("⌨", "Keyboard Shortcuts", self._show_shortcuts),
            ("🎨", f"Theme · {THEME['name']}", self._show_themes),
            ("⌂", "Go home", self._go_home),
            ("⎘", "Copy last prompt + reply", app.action_copy_last),
            ("⎘", "Copy whole chat", app.action_copy_all),
            ("♪", "Sound play / stop", app.action_toggle_sound),
            ("🧹", "Clear chat timeline", app.action_clear_chat),
            ("⌫", "Clear input line", app.action_clear_input),
            ("✕", "Close menu", self.dismiss_palette),
        ]

    def _entry_markup(self, entry: dict[str, Any], selected: bool) -> Text:
        """Build a row's Text with EXPLICIT colors on every segment."""
        kind = entry["kind"]
        accent = THEME["accent"]
        if kind == "command":
            icon, label = entry["icon"], entry["label"]
            if selected:
                return Text.from_markup(
                    f"[{accent}]›[/] [{accent}]{icon}[/]  [bold #f5f6fc]{escape(label)}[/]"
                )
            return Text.from_markup(
                f"[#3a4157]›[/] [#aab2c7]{icon}[/]  [#dbe0ee]{escape(label)}[/]"
            )
        if kind == "theme":
            name = entry["label"]
            spec = THEMES.get(name, {})
            active = name == THEME["name"]
            # Each row's dot is colored with THAT theme's accent, so the
            # user sees the palette color while browsing.
            dot_color = spec.get("accent", "#4b5163")
            suffix = "  [#34d399]active[/]" if active else ""
            if selected:
                return Text.from_markup(
                    f"[{accent}]›[/] [{dot_color}]●[/]  [bold #f5f6fc]{escape(name)}[/]{suffix}"
                )
            return Text.from_markup(
                f"[#3a4157]›[/] [{dot_color}]●[/]  [#dbe0ee]{escape(name)}[/]{suffix}"
            )
        markup = entry["markup"]
        return markup if markup is not None else Text("")

    def _add_entry(
        self,
        *,
        kind: str,
        icon: str = "",
        label: str = "",
        markup: Text | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        assert self._list is not None
        entry: dict[str, Any] = {
            "kind": kind,
            "icon": icon,
            "label": label,
            "markup": markup,
            "action": action,
            "widget": None,
        }
        widget = Static(self._entry_markup(entry, False), classes="palette-item")
        entry["widget"] = widget
        self._list.mount(widget)
        self._entries.append(entry)

    def _rebuild(self, query: str) -> None:
        assert self._list is not None
        self._list.remove_children()
        self._entries = []
        self._index = 0

        if self._mode == "shortcuts":
            if self._section is not None:
                self._section.update("Keyboard Shortcuts")
            for key, desc in self.SHORTCUT_ROWS:
                self._add_entry(
                    kind="info",
                    markup=Text.from_markup(f"{keycap(key, '')}  [#aab2c7]{escape(desc)}[/]"),
                )
            # Clear exits: esc → back to commands, ✕ → close the menu.
            self._add_entry(
                kind="info",
                markup=Text.from_markup(f"{keycap('esc', '')}  [#aab2c7]back to commands[/]"),
                action=self._show_commands,
            )
            self._add_entry(
                kind="info",
                markup=Text.from_markup("[#fb7185]✕[/]  [#dbe0ee]close the menu[/]"),
                action=self.dismiss_palette,
            )
            self._paint_selection()
            return

        if self._mode == "themes":
            if self._section is not None:
                self._section.update("Theme — ↑↓ applies live")
            for name in THEME_ORDER:
                self._add_entry(
                    kind="theme", label=name, action=lambda n=name: self._apply_theme(n)
                )
            self._add_entry(
                kind="info",
                markup=Text.from_markup(f"{keycap('esc', '')}  [#aab2c7]back to commands[/]"),
                action=self._show_commands,
            )
            self._paint_selection()
            return

        if self._section is not None:
            self._section.update("Suggested")
        query = query.strip().lower()
        matched = [
            (icon, label, action)
            for icon, label, action in self._commands()
            if not query or query in label.lower() or query in icon
        ]
        if not matched:
            self._add_entry(
                kind="info", markup=Text.from_markup("[#8a91a8]no matching commands[/]")
            )
            self._paint_selection()
            return
        for icon, label, action in matched:
            self._add_entry(kind="command", icon=icon, label=label, action=action)
        self._paint_selection()

    def _paint_selection(self) -> None:
        """Repaint every row from OUR row model — no widget internals."""
        if not self.is_mounted:
            return
        for i, entry in enumerate(self._entries):
            widget: Static = entry["widget"]
            selected = i == self._index and entry["action"] is not None
            if selected:
                widget.add_class("selected")
            else:
                widget.remove_class("selected")
            widget.update(self._entry_markup(entry, selected))

    # navigation (unique names — Screen carries selection APIs like
    # ``clear_selection`` that must never be shadowed) ───────────────────

    def palette_move(self, delta: int) -> None:
        """Move selection; in the THEME view this APPLIES LIVE as you move."""
        indices = [i for i, e in enumerate(self._entries) if e["action"] is not None]
        if not indices:
            return
        if self._index not in indices:
            self._index = indices[0]
            self._paint_selection()
            return
        current = indices.index(self._index)
        self._index = indices[(current + delta) % len(indices)]

        if self._mode == "themes":
            entry = self._entries[self._index]
            if entry["kind"] == "theme":
                jimmy(self).set_theme(entry["label"])

        self._paint_selection()

    def palette_escape(self) -> None:
        """esc: submenu → back to commands · commands → close."""
        if self._mode != "commands":
            self._show_commands()
            return
        self.dismiss_palette()

    def action_palette_escape_action(self) -> None:
        self.palette_escape()

    # input / events ───────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "palette-search" and self._mode == "commands":
            self._rebuild(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "palette-search":
            return
        event.stop()
        self._run_index()

    def on_key(self, event: events.Key) -> None:
        # Backup path for when the search box ISN'T focused.
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.palette_escape()
        elif event.key == "up":
            event.stop()
            event.prevent_default()
            self.palette_move(-1)
        elif event.key == "down":
            event.stop()
            event.prevent_default()
            self.palette_move(1)

    def on_click(self, event: events.Click) -> None:
        control = event.control
        if control is None:
            return
        # 1) the ✕ button in the header
        if getattr(control, "id", None) == "palette-close":
            event.stop()
            self.dismiss_palette()
            return
        # 2) a row → activate it
        for index, entry in enumerate(self._entries):
            if control is entry["widget"]:
                event.stop()
                if entry["action"] is not None:
                    self._index = index
                    self._paint_selection()
                    self._run_index()
                return
        # 3) click OUTSIDE the card (the dim scrim) → close.  Walk the
        #    ancestor chain: if we never reach #palette, it was the scrim.
        node: Any = control
        inside = False
        while node is not None:
            if getattr(node, "id", None) == "palette":
                inside = True
                break
            node = node.parent
        if not inside:
            self.dismiss_palette()

    def _run_index(self) -> None:
        if 0 <= self._index < len(self._entries):
            action = self._entries[self._index]["action"]
            if action is not None:
                action()

    # command actions ────────────────────────────────────────────────────

    def _show_shortcuts(self) -> None:
        self._mode = "shortcuts"
        self._rebuild("")

    def _show_themes(self) -> None:
        self._mode = "themes"
        self._rebuild("")

    def _show_commands(self) -> None:
        self._mode = "commands"
        query = self._search.value if self._search is not None else ""
        self._rebuild(query)

    def _apply_theme(self, name: str) -> None:
        """↵ / click on a theme row — apply, then return to commands."""
        jimmy(self).set_theme(name)
        self._show_commands()

    # closing ──────────────────────────────────────────────────────────────

    def dismiss_palette(self) -> None:
        """The single close path — delegates to the app (canonical pop +
        explicit focus restore).  No timers, no dismiss(), no races."""
        jimmy(self).close_palette()

    def _go_home(self) -> None:
        """Close the palette FIRST, then navigate home (order-safe)."""
        app = jimmy(self)

        def _navigate() -> None:
            app.action_home()

        try:
            app.close_palette(after=_navigate)  # app.py with `after` param
        except TypeError:
            app.close_palette()  # older app.py fallback
            app.call_later(_navigate)
