"""🎛️ ctrl+p command palette — small, centered, focused.

Root menu contains only:
    ⌨ Keyboard Shortcuts
    🎨 Theme
    🤖 Change model   → opens the ModelScreen wizard (the ONE model UI —
       saved models re-read fresh on every open, search every provider,
       same-key instant switch).  There is deliberately NO inline model
       list here: it duplicated the wizard and could show stale state.
    🛡️ Permissions    → opens the permission-mode picker (ask / auto /
       full access).  The current mode label is recomputed on EVERY
       rebuild, exactly like the model label — never stale.
    ✕ Close menu

The CURRENT model is shown in the header and the section line, and is
re-computed on EVERY rebuild — so after a wizard switch it is always
fresh (the palette never caches it).

Submenus:
    shortcuts → keyboard reference
    themes    → live theme picker

esc hierarchy: submenu → back to commands · active search → clear it ·
root → close.  The palette owns only palette-related behavior.
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

from tui.screens.sessions import SessionsScreen

from ..kit.helpers import jimmy, keycap
from ..kit.theme import THEME, THEME_ORDER, THEMES
from .models import ModelScreen
from .permissions import PermissionScreen  # 🛡️ permission-mode picker


class PaletteSearch(Input):
    """🔍 Search box with reliable keyboard navigation."""

    def on_key(self, event: events.Key) -> None:
        screen = cast(
            CommandPaletteScreen,
            self.screen,
        )

        if event.key == "escape":
            event.stop()
            event.prevent_default()
            screen.palette_escape()

        elif event.key == "up":
            event.stop()
            event.prevent_default()
            screen.palette_move(-1)

        elif event.key == "down":
            event.stop()
            event.prevent_default()
            screen.palette_move(1)

        elif event.key == "enter":
            event.stop()
            event.prevent_default()
            screen.palette_activate()


class CommandPaletteScreen(ModalScreen):
    """🎛️ Small command palette with only essential actions."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding(
            "escape",
            "palette_escape_action",
            "Close",
            priority=True,
        ),
    ]

    SHORTCUT_ROWS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("↵", "send · begin"),
        ("/", "slash menu (autocomplete in the prompt)"),
        ("↑ ↓", "prompt history / menu navigation"),
        ("esc", "interrupt jimmy / go back in menus"),
        ("ctrl+n", "home"),
        ("ctrl+p", "command menu"),
        ("ctrl+m", "model picker"),
        ("ctrl+c", "copy last prompt + reply (incl. tool calls)"),
        ("ctrl+a", "copy whole chat"),
        ("ctrl+l", "clear input line"),
        ("ctrl+s", "sound play / stop"),
        ("ctrl+q", "quit"),
        ("drag", "mouse-select text to copy"),
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

    # ─────────────────────────────────────────────
    # 🧱 Layout
    # ─────────────────────────────────────────────

    def compose(self) -> Any:
        with Vertical(id="palette"):
            with Horizontal(id="palette-head"):
                yield Static(
                    "",
                    id="palette-title",
                )

                yield Static(
                    Text.from_markup(
                        keycap(
                            "esc",
                            "close",
                        )
                    ),
                    id="palette-esc",
                )

                yield Static(
                    "✕",
                    id="palette-close",
                )

            yield PaletteSearch(
                placeholder="🔍  Search commands…",
                id="palette-search",
            )

            yield Static(
                "Suggested",
                id="palette-section",
            )

            yield Vertical(id="palette-list")

            yield Static(
                "↑↓ navigate · ↵ select · esc back/close · click outside closes",
                id="palette-foot",
            )

    def on_mount(self) -> None:
        self._title = self.query_one(
            "#palette-title",
            Static,
        )

        self._search = self.query_one(
            "#palette-search",
            PaletteSearch,
        )

        self._list = self.query_one(
            "#palette-list",
            Vertical,
        )

        self._section = self.query_one(
            "#palette-section",
            Static,
        )

        self._paint_title()
        self._rebuild("")

        def _open() -> None:
            self._paint_selection()

            if self._search is not None:
                self._search.focus()

        self.call_after_refresh(_open)

    # ─────────────────────────────────────────────
    # 🏷️ current model (always fresh)
    # ─────────────────────────────────────────────

    def _current_model_label(self) -> str:
        """🤖 The ACTIVE model name — computed fresh on every call.

        Reads agent.provider (the hot-swapped source of truth) via the
        app helper; never raises.
        """
        try:
            return jimmy(self).current_model_short()
        except Exception:
            return "model"

    def _permission_label(self) -> str:
        """🛡️ Current permission mode — recomputed on EVERY rebuild."""
        try:
            return jimmy(self).current_permission_label()
        except Exception:
            return "permissions"

    # ─────────────────────────────────────────────
    # 🎨 Chrome
    # ─────────────────────────────────────────────

    def _paint_title(self) -> None:
        if self._title is not None:
            self._title.update(
                Text.from_markup(
                    f"[{THEME['accent']}]✦[/] [#e2e6f2]Commands[/]"
                    f"  [#2a3148]·[/] [{THEME['accent']}]🤖[/] "
                    f"[#7b8296]{escape(self._current_model_label())}[/]"
                )
            )

    def _paint_section(self, text: str) -> None:
        """Section line — carries the CURRENT model so it is visible
        without opening 🤖 (recomputed on every rebuild → always fresh).
        """
        if self._section is not None:
            self._section.update(
                Text.from_markup(
                    f"{escape(text)}  [#2a3148]·[/] "
                    f"[{THEME['accent']}]🤖[/] [#7b8296]"
                    f"{escape(self._current_model_label())}[/]"
                )
            )

    # ─────────────────────────────────────────────
    # 📋 Root commands
    # ─────────────────────────────────────────────

    def _commands(
        self,
    ) -> list[tuple[str, str, Callable[[], None]]]:
        """Root menu — only the supported actions.

        The model + permission labels are computed on EVERY rebuild, so
        they always reflect the CURRENT state.
        """

        app = jimmy(self)

        model_label = self._current_model_label()

        return [
            (
                "⌨",
                "Keyboard Shortcuts",
                self._show_shortcuts,
            ),
            (
                "🤖",
                f"Change model · {model_label}",
                self._open_model_screen,
            ),
            (
                "🛡️",
                f"Permissions · {self._permission_label()}",
                self._open_permission_screen,
            ),
            (
                "📚",
                "Sessions · browse & resume",
                self._open_sessions_screen,
            ),
            (
                "🎨",
                f"Theme · {THEME['name']}",
                self._show_themes,
            ),
            (
                "✕",
                "Close menu",
                self.dismiss_palette,
            ),
        ]

    # ─────────────────────────────────────────────
    # 🖼️ Row rendering
    # ─────────────────────────────────────────────

    def _entry_markup(
        self,
        entry: dict[str, Any],
        selected: bool,
    ) -> Text:
        """Render one row with explicit colors."""

        kind = entry["kind"]
        accent = THEME["accent"]

        if kind == "command":
            icon = entry["icon"]
            label = entry["label"]

            if selected:
                return Text.from_markup(
                    f"[{accent}]›[/] [{accent}]{icon}[/]  [bold #f5f6fc]{escape(label)}[/]"
                )

            return Text.from_markup(
                f"[#3a4157]›[/] [#aab2c7]{icon}[/]  [#dbe0ee]{escape(label)}[/]"
            )

        if kind == "theme":
            name = entry["label"]
            spec = THEMES.get(
                name,
                {},
            )

            active = name == THEME["name"]

            dot_color = spec.get(
                "accent",
                "#4b5163",
            )

            suffix = "  [#34d399]active[/]" if active else ""

            if selected:
                return Text.from_markup(
                    f"[{accent}]›[/] [{dot_color}]●[/]  [bold #f5f6fc]{escape(name)}[/]{suffix}"
                )

            return Text.from_markup(
                f"[#3a4157]›[/] [{dot_color}]●[/]  [#dbe0ee]{escape(name)}[/]{suffix}"
            )

        markup = entry.get("markup")

        if isinstance(markup, Text):
            return markup

        return Text("")

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

        widget = Static(
            self._entry_markup(
                entry,
                False,
            ),
            classes="palette-item",
        )

        entry["widget"] = widget

        self._list.mount(widget)
        self._entries.append(entry)

    # ─────────────────────────────────────────────
    # 🔄 Rebuild current view
    # ─────────────────────────────────────────────

    def _rebuild(
        self,
        query: str,
    ) -> None:
        assert self._list is not None

        self._list.remove_children()
        self._entries.clear()
        self._index = 0

        # ─────────────────────────────────────────
        # ⌨️ shortcuts
        # ─────────────────────────────────────────

        if self._mode == "shortcuts":
            if self._section is not None:
                self._section.update("Keyboard Shortcuts")

            for key, description in self.SHORTCUT_ROWS:
                self._add_entry(
                    kind="info",
                    markup=Text.from_markup(
                        f"{keycap(key, '')}  [#aab2c7]{escape(description)}[/]"
                    ),
                )

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

        # ─────────────────────────────────────────
        # 🎨 themes
        # ─────────────────────────────────────────

        if self._mode == "themes":
            if self._section is not None:
                self._section.update("Theme — ↑↓ applies live")

            for name in THEME_ORDER:
                self._add_entry(
                    kind="theme",
                    label=name,
                    action=lambda n=name: self._apply_theme(n),
                )

            self._add_entry(
                kind="info",
                markup=Text.from_markup(f"{keycap('esc', '')}  [#aab2c7]back to commands[/]"),
                action=self._show_commands,
            )

            self._paint_selection()
            return

        # ─────────────────────────────────────────
        # 🎛️ root commands — 🤖 model label recomputed here, so it is
        #    fresh after every wizard switch.
        # ─────────────────────────────────────────

        self._paint_section("Suggested")

        search = query.strip().lower()

        matched = [
            (
                icon,
                label,
                action,
            )
            for icon, label, action in self._commands()
            if (not search or search in label.lower() or search in icon)
        ]

        if not matched:
            self._add_entry(
                kind="info",
                markup=Text.from_markup("[#8a91a8]no matching commands[/]"),
            )

            self._paint_selection()
            return

        for icon, label, action in matched:
            self._add_entry(
                kind="command",
                icon=icon,
                label=label,
                action=action,
            )

        self._paint_selection()

    # ─────────────────────────────────────────────
    # 🎯 Selection
    # ─────────────────────────────────────────────

    def _paint_selection(self) -> None:
        if not self.is_mounted:
            return

        for i, entry in enumerate(self._entries):
            widget: Static = entry["widget"]

            selected = i == self._index and entry["action"] is not None

            if selected:
                widget.add_class("selected")

                try:
                    widget.scroll_visible(animate=False)
                except Exception:
                    pass

            else:
                widget.remove_class("selected")

            widget.update(
                self._entry_markup(
                    entry,
                    selected,
                )
            )

    # ─────────────────────────────────────────────
    # ⌨️ Navigation
    # ─────────────────────────────────────────────

    def palette_move(
        self,
        delta: int,
    ) -> None:
        """Move the current selection."""

        indices = [i for i, entry in enumerate(self._entries) if entry["action"] is not None]

        if not indices:
            return

        if self._index not in indices:
            self._index = indices[0]
            self._paint_selection()
            return

        current = indices.index(self._index)

        self._index = indices[(current + delta) % len(indices)]

        # 🎨 Themes apply immediately while browsing.
        if self._mode == "themes":
            entry = self._entries[self._index]

            if entry["kind"] == "theme":
                jimmy(self).set_theme(entry["label"])

        self._paint_selection()

    def palette_activate(self) -> None:
        """Activate the selected row."""

        self._run_index()

    def palette_escape(self) -> None:
        """Esc = back from submenu, close from root.

        If the search box has text, esc clears it first — the search
        never eats your place.
        """
        if self._mode != "commands":
            self._show_commands()
            return

        if self._search is not None and self._search.value.strip():
            self._search.value = ""
            self._rebuild("")
            return

        self.dismiss_palette()

    def action_palette_escape_action(self) -> None:
        self.palette_escape()

    # ─────────────────────────────────────────────
    # ⌨️ Input
    # ─────────────────────────────────────────────

    def on_input_changed(
        self,
        event: Input.Changed,
    ) -> None:
        if event.input.id == "palette-search" and self._mode == "commands":
            self._rebuild(event.value)

    def on_input_submitted(
        self,
        event: Input.Submitted,
    ) -> None:
        if event.input.id != "palette-search":
            return

        event.stop()
        self.palette_activate()

    def on_key(
        self,
        event: events.Key,
    ) -> None:
        # Backup path when search doesn't hold focus.
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

        elif event.key == "enter":
            event.stop()
            event.prevent_default()
            self.palette_activate()

    # ─────────────────────────────────────────────
    # 🖱️ Mouse
    # ─────────────────────────────────────────────

    def on_click(
        self,
        event: events.Click,
    ) -> None:
        control = event.control

        if control is None:
            return

        # ✕ Header button.
        if (
            getattr(
                control,
                "id",
                None,
            )
            == "palette-close"
        ):
            event.stop()
            self.dismiss_palette()
            return

        # Row click.
        for index, entry in enumerate(self._entries):
            if control is entry["widget"]:
                event.stop()

                if entry["action"] is not None:
                    self._index = index
                    self._paint_selection()
                    self._run_index()

                return

        # Click outside the card.
        node: Any = control

        while node is not None:
            if (
                getattr(
                    node,
                    "id",
                    None,
                )
                == "palette"
            ):
                return

            node = getattr(
                node,
                "parent",
                None,
            )

        self.dismiss_palette()

    # ─────────────────────────────────────────────
    # ▶️ Commands
    # ─────────────────────────────────────────────

    def _run_index(self) -> None:
        if not (0 <= self._index < len(self._entries)):
            return

        action = self._entries[self._index]["action"]

        if action is not None:
            action()

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

    def _apply_theme(
        self,
        name: str,
    ) -> None:
        """Apply theme and return to root commands (🤖 label refreshes)."""

        jimmy(self).set_theme(name)
        self._show_commands()

    def _open_model_screen(self) -> None:
        """🤖 Change model → close palette first, then open ModelScreen.

        The wizard re-reads saved models and the active model on every
        mount, so it can never show stale state.
        """

        app = jimmy(self)

        def _open() -> None:
            app.push_screen(ModelScreen())

        try:
            app.close_palette(after=_open)

        except TypeError:
            app.close_palette()
            app.call_later(_open)

    def _open_permission_screen(self) -> None:
        """🛡️ Permissions → close palette first, then open the picker."""

        app = jimmy(self)

        def _open() -> None:
            app.push_screen(PermissionScreen())

        try:
            app.close_palette(after=_open)

        except TypeError:
            app.close_palette()
            app.call_later(_open)
            

    def _open_sessions_screen(self) -> None:
        """📚 Sessions → close palette first, then open the library."""

        app = jimmy(self)

        def _open() -> None:
            app.push_screen(SessionsScreen())

        try:
            app.close_palette(after=_open)

        except TypeError:
            app.close_palette()
            app.call_later(_open)

    # ─────────────────────────────────────────────
    # ✕ Closing
    # ─────────────────────────────────────────────

    def dismiss_palette(self) -> None:
        """Canonical palette close path."""

        jimmy(self).close_palette()
