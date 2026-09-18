"""🤖 Model picker — live catalog, zero hard-coded model lists.

Flow:
    Provider → Model → API key → Save & switch

Views:
    list     → saved models + ➕ add + 🔄 refresh
    provider → ⭐ popular models + providers + cross-search
    model    → ⭐ popular for provider + all models + custom
    key      → API key input

Discovery is delegated to jimmy.llm.catalog.
New providers/models appear without changing this UI.
"""

from __future__ import annotations

import os
from typing import Any, Callable, ClassVar, cast

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from jimmy.llm.catalog import (
    Catalog,
    get_catalog,
    save_key_to_env,
)
from jimmy.llm.catalog import (
    search as catalog_search,
)
from jimmy.llm.model_config import ModelConfig, ModelStore

from ..kit.helpers import jimmy, keycap, short_model
from ..kit.theme import THEME


class ModelSearch(Input):
    """🔍 Search input that owns navigation keys while focused."""

    def on_key(self, event: events.Key) -> None:
        screen = cast(ModelScreen, self.screen)

        if event.key == "escape":
            event.stop()
            event.prevent_default()
            screen.action_close()

        elif event.key == "up":
            event.stop()
            event.prevent_default()
            screen.model_move(-1)

        elif event.key == "down":
            event.stop()
            event.prevent_default()
            screen.model_move(1)

        elif event.key == "enter":
            event.stop()
            event.prevent_default()
            screen.model_activate()


class ModelScreen(ModalScreen):
    """🤖 Pick or add a model — live catalog, provider → model → key."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding(
            "escape",
            "close",
            "Close",
            priority=True,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(id="model-screen")

        self._mode = "list"  # list | provider | model | key
        self._index = 0

        self._rows: list[dict[str, Any]] = []

        self._catalog: Catalog | None = None

        # 🏢 Provider token, e.g. "openai"
        self._provider = ""

        # 🏷️ Full LiteLLM model string, e.g. "openai/gpt-5"
        self._model_name = ""

        # 🧩 Widgets are bound in on_mount.
        self._list: Vertical | None = None
        self._section: Static | None = None
        self._search: ModelSearch | None = None
        self._key_box: Vertical | None = None
        self._in_key: Input | None = None
        self._key_hint: Static | None = None
        self._foot: Static | None = None

    # ─────────────────────────────────────────────
    # 🧱 layout
    # ─────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Vertical(id="model-card"):
            with Horizontal(id="model-head"):
                yield Static(
                    Text.from_markup(f"[{THEME['accent']}]🤖[/] [#e2e6f2]Models[/]"),
                    id="model-title",
                )

                yield Static(
                    Text.from_markup(keycap("esc", "back/close")),
                    id="model-esc",
                )

            yield Static(
                "Saved models",
                id="model-section",
            )

            yield ModelSearch(
                placeholder="🔍  Search providers & models…",
                id="model-search",
            )

            yield Vertical(id="model-list")

            # 🔑 Key step
            with Vertical(id="model-key"):
                yield Static(
                    "",
                    id="model-fullname",
                )

                yield Static(
                    "",
                    id="model-key-hint",
                )

                with Horizontal(id="model-key-row"):
                    yield Input(
                        placeholder="Paste your API key here…",
                        password=True,
                        id="model-in-key",
                    )

                    yield Static(
                        "👁 show",
                        id="model-eye",
                    )

                yield Static(
                    "",
                    id="model-form-msg",
                )

                with Horizontal(id="model-form-actions"):
                    yield Static(
                        "  💾  Save & switch",
                        id="model-save",
                        classes="model-btn",
                    )

                    yield Static(
                        "  🔄  Refresh catalog",
                        id="model-refresh",
                        classes="model-btn",
                    )

            yield Static(
                "",
                id="model-foot",
            )

    # ─────────────────────────────────────────────
    # lifecycle
    # ─────────────────────────────────────────────

    def on_mount(self) -> None:
        """Bind real widgets after Textual has mounted the DOM."""

        self._list = self.query_one(
            "#model-list",
            Vertical,
        )

        self._section = self.query_one(
            "#model-section",
            Static,
        )

        self._search = self.query_one(
            "#model-search",
            ModelSearch,
        )

        self._key_box = self.query_one(
            "#model-key",
            Vertical,
        )

        self._in_key = self.query_one(
            "#model-in-key",
            Input,
        )

        self._key_hint = self.query_one(
            "#model-key-hint",
            Static,
        )

        self._foot = self.query_one(
            "#model-foot",
            Static,
        )

        eye = self.query_one(
            "#model-eye",
            Static,
        )
        eye.tooltip = "show / hide API key"

        self._show_list()

    # ─────────────────────────────────────────────
    # 🧰 row helpers
    # ─────────────────────────────────────────────

    def _clear_rows(self) -> None:
        assert self._list is not None

        self._list.remove_children()
        self._rows.clear()
        self._index = 0

    def _mount_row(
        self,
        markup: Text,
        action: Callable[[], None] | None = None,
    ) -> None:
        assert self._list is not None

        row = Static(
            markup,
            classes="model-row",
        )

        self._list.mount(row)

        self._rows.append(
            {
                "widget": row,
                "action": action,
                "markup": markup,
            }
        )

    def _paint_selection(self) -> None:
        for i, row in enumerate(self._rows):
            widget: Static = row["widget"]

            if i == self._index and row["action"] is not None:
                widget.add_class("selected")

                try:
                    widget.scroll_visible(animate=False)
                except Exception:
                    pass
            else:
                widget.remove_class("selected")

    def _move(self, delta: int) -> None:
        selectable = [i for i, row in enumerate(self._rows) if row["action"] is not None]

        if not selectable:
            return

        if self._index not in selectable:
            self._index = selectable[0]
        else:
            current = selectable.index(self._index)

            self._index = selectable[(current + delta) % len(selectable)]

        self._paint_selection()

    # ─────────────────────────────────────────────
    # 🧭 mode
    # ─────────────────────────────────────────────

    def _set_mode(
        self,
        mode: str,
        section: str,
        *,
        search: bool,
    ) -> None:
        self._mode = mode

        if self._section is not None:
            self._section.update(section)

        if self._search is not None:
            self._search.display = search
            self._search.value = ""

        if self._key_box is not None:
            self._key_box.display = mode == "key"

        if self._foot is not None:
            hints = {
                "list": "↑↓ navigate · ↵ switch · ➕ add · esc close",
                "provider": "🔍 search · ↑↓ navigate · ↵ select · esc back",
                "model": "🔍 search · ↑↓ navigate · ↵ select · esc back",
                "key": "paste key · ↵ save · 👁 show/hide · esc back",
            }

            self._foot.update(Text.from_markup(f"[#565d73]{hints.get(mode, '')}[/]"))

    def _ensure_catalog(
        self,
        *,
        force: bool = False,
    ) -> Catalog:
        if self._catalog is None or force:
            self._catalog = get_catalog(force=force)

        return self._catalog

    # ─────────────────────────────────────────────
    # 📋 saved models
    # ─────────────────────────────────────────────

    def _show_list(self) -> None:
        self._set_mode(
            "list",
            "Saved models — ↵ switch · ➕ add · 🔄 refresh",
            search=False,
        )

        assert self._list is not None

        self._list.display = True

        if self._key_box is not None:
            self._key_box.display = False

        self._clear_rows()

        store = ModelStore()

        for model in store.load():
            if model.is_active:
                dot = "[#34d399]●[/]"
                suffix = "  [#34d399]active[/]"
            else:
                dot = "[#3a4157]○[/]"
                suffix = ""

            self._mount_row(
                Text.from_markup(
                    f"{dot}  "
                    f"[#dbe0ee]"
                    f"{escape(short_model(model.name))}"
                    f"[/]  "
                    f"[#565d73]"
                    f"{escape(model.name)}"
                    f"[/]"
                    f"{suffix}"
                ),
                self._make_switch(model.name),
            )

        self._mount_row(
            Text.from_markup(f"[{THEME['accent']}]➕[/] [#dbe0ee]Add a model…[/]"),
            self._show_providers,
        )

        self._mount_row(
            Text.from_markup(f"[{THEME['accent']}]🔄[/] [#dbe0ee]Refresh model catalog[/]"),
            self._refresh,
        )

        self._paint_selection()

    def _make_switch(
        self,
        name: str,
    ) -> Callable[[], None]:
        def _do() -> None:
            try:
                jimmy(self).switch_model(name)
                self.app.pop_screen()

            except Exception:
                # 🔑 Probably missing API key.
                store = ModelStore()

                cfg = next(
                    (model for model in store.load() if model.name == name),
                    None,
                )

                if cfg is not None:
                    self._model_name = name
                    self._provider = name.split("/", 1)[0]

                    self._show_key(prefill_env=cfg.api_key_env)
                else:
                    self._show_providers()

        return _do

    # ─────────────────────────────────────────────
    # 🏢 provider picker
    # ─────────────────────────────────────────────

    def _show_providers(self) -> None:
        self._set_mode(
            "provider",
            "⭐ popular · providers · 🔍 search",
            search=True,
        )

        assert self._list is not None

        self._list.display = True

        if self._key_box is not None:
            self._key_box.display = False

        self._rebuild_providers("")

        if self._search is not None:
            self._search.focus()

    def _rebuild_providers(
        self,
        query: str,
    ) -> None:
        catalog = self._ensure_catalog()

        self._clear_rows()

        q = query.strip().lower()

        providers, models = catalog_search(
            catalog,
            q,
        )

        # ⭐ Popular models first.
        for full in catalog.popular:
            if q and q not in full.lower():
                continue

            provider = full.split("/", 1)[0] if "/" in full else ""

            self._mount_row(
                Text.from_markup(
                    f"[#f5c451]⭐[/] "
                    f"[#dbe0ee]"
                    f"{escape(short_model(full))}"
                    f"[/]  "
                    f"[#565d73]"
                    f"{escape(full)}"
                    f"[/]"
                ),
                lambda f=full, p=provider: self._model_chosen(
                    f,
                    p,
                ),
            )

        # 🏢 Providers.
        for provider in providers:
            count = len(
                catalog.providers.get(
                    provider,
                    [],
                )
            )

            self._mount_row(
                Text.from_markup(
                    f"[{THEME['accent']}]▸[/] "
                    f"[#dbe0ee]"
                    f"{escape(provider)}"
                    f"[/]  "
                    f"[#565d73]"
                    f"{count} models"
                    f"[/]"
                ),
                lambda p=provider: self._show_models(p),
            )

        # 🔎 Direct model matches.
        for full in models:
            if full in catalog.popular:
                continue

            provider = full.split("/", 1)[0] if "/" in full else ""

            self._mount_row(
                Text.from_markup(
                    f"[#dbe0ee]{escape(short_model(full))}[/]  [#565d73]{escape(full)}[/]"
                ),
                lambda f=full, p=provider: self._model_chosen(
                    f,
                    p,
                ),
            )

        if not self._rows:
            self._mount_row(Text.from_markup("[#8a91a8]no match — try another name[/]"))

        self._paint_selection()

    # ─────────────────────────────────────────────
    # 🧠 model picker
    # ─────────────────────────────────────────────

    def _show_models(
        self,
        provider: str,
    ) -> None:
        self._provider = provider

        self._set_mode(
            "model",
            f"{provider} — pick a model 🔍",
            search=True,
        )

        assert self._list is not None

        self._list.display = True

        if self._key_box is not None:
            self._key_box.display = False

        self._rebuild_models("")

        if self._search is not None:
            self._search.focus()

    def _rebuild_models(
        self,
        query: str,
    ) -> None:
        catalog = self._ensure_catalog()

        self._clear_rows()

        q = query.strip().lower()

        models = catalog.providers.get(
            self._provider,
            [],
        )

        popular_here = [
            model
            for model in catalog.popular
            if ("/" in model and model.split("/", 1)[0] == self._provider)
        ]

        # ⭐ Popular models for this provider.
        for full in popular_here:
            if q and q not in full.lower():
                continue

            model_name = full.split(
                "/",
                1,
            )[-1]

            self._mount_row(
                Text.from_markup(f"[#f5c451]⭐[/] [#dbe0ee]{escape(model_name)}[/]"),
                lambda f=full: self._model_chosen(
                    f,
                    self._provider,
                ),
            )

        # 📋 All remaining models.
        for full in models:
            if full in popular_here:
                continue

            if q and q not in full.lower():
                continue

            model_name = full.split(
                "/",
                1,
            )[-1]

            self._mount_row(
                Text.from_markup(f"[#dbe0ee]{escape(model_name)}[/]"),
                lambda f=full: self._model_chosen(
                    f,
                    self._provider,
                ),
            )

        # ✍️ Custom model.
        self._mount_row(
            Text.from_markup("[#8a91a8]✍️ use the typed name as a custom model…[/]"),
            self._use_custom,
        )

        if not self._rows:
            self._mount_row(Text.from_markup("[#8a91a8]no match — use custom[/]"))

        self._paint_selection()

    def _use_custom(self) -> None:
        """✍️ Build provider/model from the search text."""

        assert self._search is not None

        typed = self._search.value.strip()

        if not typed:
            self._search.focus()
            return

        # If the user already typed provider/model,
        # don't duplicate the provider prefix.
        if "/" in typed:
            full = typed
            provider = typed.split(
                "/",
                1,
            )[0]
        else:
            provider = self._provider
            full = f"{provider}/{typed}" if provider else typed

        self._model_chosen(
            full,
            provider,
        )

    def _model_chosen(
        self,
        full: str,
        provider: str,
    ) -> None:
        self._model_name = full
        self._provider = provider
        self._show_key()

    # ─────────────────────────────────────────────
    # 🔑 API key
    # ─────────────────────────────────────────────

    def _show_key(
        self,
        prefill_env: str = "",
    ) -> None:
        self._set_mode(
            "key",
            "API key — paste · 💾 save",
            search=False,
        )

        assert self._list is not None

        self._list.display = False

        if self._key_box is not None:
            self._key_box.display = True

        catalog = self._ensure_catalog()

        env_var = prefill_env or catalog.provider_env_var(self._provider)

        api_base = catalog.provider_api_base(self._provider)

        fullname = self.query_one(
            "#model-fullname",
            Static,
        )

        fullname.update(
            Text.from_markup(
                f"[#e2e6f2]"
                f"{escape(short_model(self._model_name))}"
                f"[/]  "
                f"[#565d73]"
                f"{escape(self._model_name)}"
                f"[/]"
            )
        )

        if self._key_hint is not None:
            if not env_var:
                self._key_hint.update(
                    Text.from_markup("[#34d399]No API key needed — just save.[/]")
                )
            else:
                already = "✅ already set in environment" if os.environ.get(env_var) else ""

                self._key_hint.update(
                    Text.from_markup(
                        "[#aab2c7]Key saved to[/] "
                        "[#565d73]~/.jimmy/.env[/] "
                        "[#aab2c7]as[/] "
                        f"[#f5c451]"
                        f"{escape(env_var)}"
                        f"[/] "
                        f"{already}"
                    )
                )

        msg = self.query_one(
            "#model-form-msg",
            Static,
        )

        if api_base:
            msg.update(Text.from_markup(f"[#565d73]🌐 endpoint: {escape(api_base)}[/]"))
        else:
            msg.update("")

        if self._in_key is not None:
            self._in_key.value = ""
            self._in_key.focus()

    # ─────────────────────────────────────────────
    # 💾 save
    # ─────────────────────────────────────────────

    def _save(self) -> None:
        """💾 Validate → save/update config → activate → hot-swap."""

        app = jimmy(self)

        # ✅ Validate model selection FIRST.
        # This must happen before using provider.
        name = self._model_name.strip()

        msg = self.query_one(
            "#model-form-msg",
            Static,
        )

        if not name:
            msg.update(Text.from_markup("[#fb7185]✕ no model selected[/]"))
            return

        # 🏢 Provider may be empty/invalid for a custom model.
        provider = self._provider.strip()

        catalog = self._ensure_catalog()

        # 🔑 Only ask catalog for provider metadata when we
        # actually have a provider.
        if provider:
            env_var = catalog.provider_env_var(provider)
            api_base = catalog.provider_api_base(provider) or None
        else:
            env_var = ""
            api_base = None

        key = self._in_key.value.strip() if self._in_key is not None else ""

        # 🔑 Save pasted key.
        if env_var and key:
            save_key_to_env(
                env_var,
                key,
            )

        # 🔐 Provider needs a key, but we don't have one.
        elif env_var and not os.environ.get(env_var):
            msg.update(
                Text.from_markup(
                    f"[#fb7185]✕ paste the key (or set {escape(env_var)} in ~/.jimmy/.env)[/]"
                )
            )
            return

        try:
            store = app.model_store
            models = store.load()

            existing = next(
                (model for model in models if model.name == name),
                None,
            )

            config = ModelConfig(
                name=name,
                api_key_env=env_var,
                api_base=api_base,
                is_active=(existing.is_active if existing is not None else False),
            )

            if existing is None:
                # ➕ New model.
                store.add(config)
            else:
                # ✏️ Update existing model configuration.
                updated = [config if model.name == name else model for model in models]

                store.save(updated)

            # 🔄 Make it active and hot-swap the agent.
            store.set_active(name)
            app.switch_model(name)

        except Exception as exc:
            msg.update(Text.from_markup(f"[#fb7185]✕ {escape(str(exc))}[/]"))
            return

        self.app.pop_screen()

    # ─────────────────────────────────────────────
    # 🔄 catalog refresh
    # ─────────────────────────────────────────────

    def _refresh(self) -> None:
        """🔄 Force fresh provider/model discovery."""

        self._catalog = get_catalog(force=True)

        if self._mode == "model":
            query = self._search.value if self._search is not None else ""

            self._rebuild_models(query)

        elif self._mode == "provider":
            query = self._search.value if self._search is not None else ""

            self._rebuild_providers(query)

        else:
            # From list, stay on list.
            self._show_list()

        self.notify(
            "🌐 catalog refreshed",
            timeout=1.5,
        )

    # ─────────────────────────────────────────────
    # ⌨️ events
    # ─────────────────────────────────────────────

    def on_input_changed(
        self,
        event: Input.Changed,
    ) -> None:
        if event.input.id != "model-search":
            return

        if self._mode == "provider":
            self._rebuild_providers(event.value)

        elif self._mode == "model":
            self._rebuild_models(event.value)

    def on_input_submitted(
        self,
        event: Input.Submitted,
    ) -> None:
        event.stop()

        if event.input.id == "model-search":
            self._activate()

        elif event.input.id == "model-in-key":
            self._save()

    def on_key(
        self,
        event: events.Key,
    ) -> None:
        # Backup when search input isn't focused.
        if event.key == "up":
            event.stop()
            event.prevent_default()
            self.model_move(-1)

        elif event.key == "down":
            event.stop()
            event.prevent_default()
            self.model_move(1)

        elif event.key == "enter":
            event.stop()
            event.prevent_default()

            if self._mode == "key":
                self._save()
            else:
                self.model_activate()

    # ─────────────────────────────────────────────
    # public navigation API
    # ─────────────────────────────────────────────

    def model_move(
        self,
        delta: int,
    ) -> None:
        self._move(delta)

    def model_activate(self) -> None:
        self._activate()

    def _activate(self) -> None:
        if not (0 <= self._index < len(self._rows)):
            return

        action = self._rows[self._index]["action"]

        if action is not None:
            action()

    # ─────────────────────────────────────────────
    # 👁 key visibility
    # ─────────────────────────────────────────────

    def _toggle_eye(self) -> None:
        """👁 Show/hide pasted API key."""

        if self._in_key is None:
            return

        eye = self.query_one(
            "#model-eye",
            Static,
        )

        self._in_key.password = not self._in_key.password

        eye.update("🙈 hide" if not self._in_key.password else "👁 show")

    # ─────────────────────────────────────────────
    # 🖱️ mouse
    # ─────────────────────────────────────────────

    def on_click(
        self,
        event: events.Click,
    ) -> None:
        control = event.control

        if control is None:
            return

        cid = getattr(
            control,
            "id",
            None,
        )

        if cid == "model-save":
            event.stop()
            self._save()
            return

        if cid == "model-refresh":
            event.stop()
            self._refresh()
            return

        if cid == "model-eye":
            event.stop()
            self._toggle_eye()
            return

        for i, row in enumerate(self._rows):
            if control is row["widget"]:
                event.stop()

                self._index = i
                self._activate()

                return

        # 🖱️ Click outside card → close.
        node: Any = control

        while node is not None:
            if (
                getattr(
                    node,
                    "id",
                    None,
                )
                == "model-card"
            ):
                return

            node = getattr(
                node,
                "parent",
                None,
            )

        self.app.pop_screen()

    # ─────────────────────────────────────────────
    # ⌨️ escape navigation
    # ─────────────────────────────────────────────

    def action_close(self) -> None:
        """esc: key → model → provider → list → close."""

        if self._mode == "key":
            if self._provider:
                self._show_models(self._provider)
            else:
                self._show_providers()

        elif self._mode == "model":
            self._show_providers()

        elif self._mode == "provider":
            self._show_list()

        else:
            self.app.pop_screen()
