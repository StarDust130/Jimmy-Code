"""🤖 Model picker — live catalog, search-first UX.

Flow:
    list → (search anywhere, or ➕ browse) → model → key (only if missing)

    🔑 SAME-API RULE: if the provider's key is already set (or not
    needed), picking a model switches INSTANTLY — no key form.

🔍 SEARCH IS ALWAYS ON — and it is MODE-AWARE:
    * saved-list view  → query shows global results: providers first
      (with "showing its N models below ↴"), then ⭐ popular, then
      fuzzy model matches, then ✍️ custom.
    * provider view    → query fuzzy-filters THAT provider's models —
      clicking "▸ chatgpt — showing its 14 models below" opens exactly
      those 14, ranked best-first (never the global search again).
    * model view       → same scoped filtering while you refine.
    * provider-browse  → query filters providers + cross-search.

    Esc always de-grades one step: scoped filter → full provider list →
    provider browse → saved list → close.  The search never eats your
    place.

Search performance: results are collected first and capped at
``_MAX_RESULTS`` rendered rows with an "…and N more" hint — typing
stays instant even against a 3,500-model registry.  Model names always
render via short_model(), so nested ids like
``groq/meta-llama/llama-prompt-guard-2-22m`` display correctly.

The fuzzy scorer lives IN THIS FILE on purpose: the picker must never
fail to import because of which search helper catalog.py exports.

Discovery is delegated to jimmy.llm.catalog (live provider APIs verify
the catalog; stale models filtered; 404'd models surfaced with ⚠).
"""

from __future__ import annotations

import asyncio
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
    is_marked_unavailable,
    save_key_to_env,
)
from jimmy.llm.model_config import ModelConfig, ModelStore

from ..kit.helpers import jimmy, keycap, short_model
from ..kit.theme import THEME

# ⌨️ footer hints per view.
_FOOT: dict[str, str] = {
    "list": "🔍 search any model · ↑↓ navigate · ↵ switch · ➕ add · esc close",
    "provider": "🔍 filter providers · ↑↓ navigate · ↵ select · esc back",
    "model": "🔍 filter these models · ↑↓ select · ↵ pick · esc back",
    "search": "↑↓ navigate · ↵ open provider / pick model · esc clears search",
    "key": "paste key · ↵ save · 👁 show/hide · esc back",
}

# 🖥️ render cap — beyond this we show "…and N more" instead of lagging.
_MAX_RESULTS = 60

_STAGES = ("provider", "model", "key")

# ─────────────────────────────────────
# 🔍 fuzzy scoring (self-contained — no catalog dependency)
# ─────────────────────────────────────


def _fuzzy_score(needle: str, haystack: str) -> int:
    """Subsequence match score.  0 = no match, higher = better.

    * exact substring → 100+ (earlier occurrence ranks higher)
    * otherwise every needle char must appear IN ORDER in the haystack
      (separators like - . _ / are skipped, so "glm flash" matches
      "glm-4.6-flash" and "gpt4o" matches "openai/gpt-4o")
    * consecutive matches and word-boundary matches score higher
    """
    if not needle:
        return 1

    if needle in haystack:
        return 100 + max(0, 40 - haystack.index(needle))

    score = 0
    hi = 0
    prev = -2
    first = True

    for ch in needle:
        found = haystack.find(ch, hi)
        if found == -1:
            return 0  # not a subsequence — no match at all
        if first:
            score += 1 + (1 if found == 0 else 0)
            first = False
        else:
            score += 2 if found == prev + 1 else 1  # consecutive chunk
            if found > 0 and haystack[found - 1] in "-._/ ":
                score += 3  # word boundary
        prev = found
        hi = found + 1

    return score


def _search_catalog(
    catalog: Catalog,
    query: str,
) -> tuple[list[str], list[str]]:
    """🔍 Fuzzy search across providers AND models — ranked best-first.

    Providers rank above models (a provider row groups its models).
    Models are scored on the FULL litellm string AND the bare model
    name, with spaces in the query ignored ("gpt 4o" works).
    """
    q = " ".join(query.lower().split())
    if not q:
        return list(catalog.providers), []

    compact = q.replace(" ", "")

    provider_hits: list[tuple[int, str]] = []
    model_hits: list[tuple[int, str]] = []

    for provider, models in catalog.providers.items():
        p_score = max(
            _fuzzy_score(q, provider),
            _fuzzy_score(compact, provider),
        )
        if p_score > 0:
            provider_hits.append((p_score + 5, provider))  # providers rank up

        for full in models:
            full_l = full.lower()
            short_l = full_l.split("/")[-1] if "/" in full_l else full_l
            s = max(
                _fuzzy_score(q, full_l),
                _fuzzy_score(q, short_l),
                _fuzzy_score(compact, full_l),
                _fuzzy_score(compact, short_l),
            )
            if s > 0:
                model_hits.append((s, full))

    provider_hits.sort(key=lambda t: t[0], reverse=True)
    model_hits.sort(key=lambda t: t[0], reverse=True)

    return (
        [p for _, p in provider_hits],
        [m for _, m in model_hits],
    )


def _crumb(parts: list[str]) -> Text:
    """Breadcrumb: Models › openai › key — the last segment is bright."""
    out = Text()
    for i, part in enumerate(parts):
        if i:
            out.append("  ›  ", style="#2a3148")
        if i == len(parts) - 1:
            out.append(part, style="bold #e2e6f2")
        else:
            out.append(part, style="#7b8296")
    return out


class ModelSearch(Input):
    """🔍 Search input that owns navigation keys while focused.

    esc → screen.action_close() which CLEARS the search first and only
    then navigates back — the search box is the primary surface.
    """

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
    """🤖 Pick or add a model — live catalog, search-first wizard."""

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

        # 🎛️ mode values kept stable: list | provider | model | key
        self._mode = "list"
        self._index = 0

        self._rows: list[dict[str, Any]] = []

        self._catalog: Catalog | None = None

        # 🏢 Provider token, e.g. "openai"
        self._provider = ""

        # 🏷️ Full LiteLLM model string, e.g. "openai/gpt-5"
        self._model_name = ""

        # ↩️ where to return after the key form (mode + provider + query)
        self._return_mode = "list"
        self._return_provider = ""
        self._prev_query = ""

        # 🧩 Widgets are bound in on_mount.
        self._list: Vertical | None = None
        self._section: Static | None = None
        self._crumb: Static | None = None
        self._steps: Static | None = None
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

            # 🧭 breadcrumb + wizard stepper
            yield Static("", id="model-crumb")
            yield Static("", id="model-steps")

            # context line: hero stats / provider label / search matches
            yield Static("", id="model-section")

            yield ModelSearch(
                placeholder="🔍  Search any provider or model…",
                id="model-search",
            )

            yield Vertical(id="model-list")

            # 🔑 Key step
            with Vertical(id="model-key"):
                yield Static("", id="model-fullname")
                yield Static("", id="model-key-hint")

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

            yield Static("", id="model-foot")

    # ─────────────────────────────────────────────
    # lifecycle
    # ─────────────────────────────────────────────

    def on_mount(self) -> None:
        """Bind real widgets after Textual has mounted the DOM."""

        self._list = self.query_one("#model-list", Vertical)
        self._section = self.query_one("#model-section", Static)
        self._crumb = self.query_one("#model-crumb", Static)
        self._steps = self.query_one("#model-steps", Static)
        self._search = self.query_one("#model-search", ModelSearch)
        self._key_box = self.query_one("#model-key", Vertical)
        self._in_key = self.query_one("#model-in-key", Input)
        self._key_hint = self.query_one("#model-key-hint", Static)
        self._foot = self.query_one("#model-foot", Static)

        eye = self.query_one("#model-eye", Static)
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

        row = Static(markup, classes="model-row")
        self._list.mount(row)
        self._rows.append({"widget": row, "action": action, "markup": markup})

    def _paint_selection(self) -> None:
        """Selection = themed › marker + highlight; deselected rows are
        restored from their stored markup (no widget internals read)."""
        accent = THEME["accent"]

        for i, row in enumerate(self._rows):
            widget: Static = row["widget"]
            selected = i == self._index and row["action"] is not None
            markup: Text = row["markup"]

            if selected:
                widget.add_class("selected")
                if not markup.plain.startswith("› "):
                    widget.update(Text("› ", style=accent) + markup)
                try:
                    widget.scroll_visible(animate=False)
                except Exception:
                    pass
            else:
                widget.remove_class("selected")
                if markup.plain.startswith("› "):
                    widget.update(markup)

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

    def _render_capped(
        self,
        entries: list[tuple[Text, Callable[[], None] | None]],
    ) -> None:
        """Render collected matches with a hard cap — search never lags.

        Beyond ``_MAX_RESULTS`` a quiet "…and N more" info row appears
        instead of hundreds of widgets; the ✍️ custom row always stays
        reachable at the bottom.
        """
        for markup, action in entries[:_MAX_RESULTS]:
            self._mount_row(markup, action)

        hidden = len(entries) - _MAX_RESULTS
        if hidden > 0:
            self._mount_row(
                Text.from_markup(
                    f"[#3a4157]…and {hidden} more[/]  [#565d73]keep typing to narrow down[/]"
                )
            )

    # ─────────────────────────────────────────────
    # 🧭 chrome helpers
    # ─────────────────────────────────────────────

    def _stepper_for(self) -> Text:
        """Wizard progress dots for the current state (blank on list)."""
        if self._mode == "key":
            pos = 2
        elif self._mode == "model":
            pos = 1
        elif self._mode == "provider":
            pos = 0
        else:
            return Text("")

        out = Text()
        for i, _stage in enumerate(_STAGES):
            if i:
                out.append(" ─ ", style="#2a3148")
            if i < pos:
                out.append("●", style="#34d399")  # completed
            elif i == pos:
                out.append("●", style=THEME["accent"])  # current
            else:
                out.append("○", style="#3a4157")  # upcoming
        return out

    def _set_chrome(
        self,
        crumb_parts: list[str],
        *,
        foot_key: str,
        search_visible: bool = True,
        steps: Text | None = None,
        section: Text | None = None,
    ) -> None:
        """Update breadcrumb / stepper / search visibility / footer.

        NOTE: the search VALUE is never touched here — it persists
        across views so the user's query is never lost.
        """
        if self._crumb is not None:
            self._crumb.update(_crumb(["Models", *crumb_parts]))

        if self._steps is not None:
            self._steps.update(steps if steps is not None else Text(""))

        if self._search is not None:
            self._search.display = search_visible

        if self._key_box is not None:
            self._key_box.display = False

        if self._foot is not None:
            self._foot.update(Text.from_markup(f"[#565d73]{_FOOT.get(foot_key, '')}[/]"))

        if section is not None and self._section is not None:
            self._section.update(section)

    def _ensure_catalog(
        self,
        *,
        force: bool = False,
    ) -> Catalog:
        if self._catalog is None or force:
            self._catalog = get_catalog(force=force)

        return self._catalog

    def _hero_line(self, catalog: Catalog) -> Text:
        """Live catalog stats shown above the saved-model list."""
        providers = len(catalog.providers)
        models = sum(len(v) for v in catalog.providers.values())
        popular = len(catalog.popular)
        verified = len(getattr(catalog, "verified", frozenset()))
        line = (
            f"[{THEME['accent']}]◈[/] [#8a91a8]live catalog[/]  "
            f"[#2a3148]·[/]  [#dbe0ee]{providers}[/][#565d73] providers[/]  "
            f"[#2a3148]·[/]  [#dbe0ee]{models}[/][#565d73] models[/]  "
            f"[#2a3148]·[/]  [#f5c451]{popular}[/][#565d73] popular[/]"
        )
        if verified:
            line += f"  [#2a3148]·[/]  [#34d399]✓ {verified} live[/]"
        return Text.from_markup(line)

    # ─────────────────────────────────────────────
    # 🔀 unified view refresh (MODE-AWARE search)
    # ─────────────────────────────────────────────

    def _refresh_view(self) -> None:
        """Render the right list for (mode, query):

        * list    + query → GLOBAL search overlay
        * provider+ query → fuzzy-filtered provider browse
        * model   + query → fuzzy-filtered THIS provider's models
        * any     + no query → that mode's native full view

        This is what makes the provider row's promise honest: clicking
        "▸ chatgpt — showing its 14 models below" opens chatgpt's view
        showing exactly those matched models — not the global search.
        """
        if self._mode == "key":
            return  # key form owns the screen until esc

        query = self._search.value.strip() if self._search is not None else ""

        if self._mode == "list":
            if query:
                self._render_search(query)
            else:
                self._chrome_list()
                self._render_saved()

        elif self._mode == "provider":
            self._chrome_providers()
            self._rebuild_providers(query)

        else:  # model
            self._chrome_models()
            self._rebuild_models(query)

    # ── per-mode chrome ──────────────────────────────────────────

    def _chrome_list(self) -> None:
        catalog = self._ensure_catalog()
        self._set_chrome(
            [],  # _set_chrome prepends "Models" — don't duplicate it
            foot_key="list",
            search_visible=True,
            steps=Text(""),
            section=self._hero_line(catalog),
        )

    def _chrome_providers(self) -> None:
        catalog = self._ensure_catalog()
        count = len(catalog.providers)
        self._set_chrome(
            ["add a model"],
            foot_key="provider",
            search_visible=True,
            steps=self._stepper_for(),
            section=Text.from_markup(
                f"[#8a91a8]choose a provider[/]  [#2a3148]·[/]  "
                f"[#dbe0ee]{count}[/][#565d73] available[/]  "
                f"[#2a3148]—[/] [#565d73]or search a model directly[/]"
            ),
        )

    def _chrome_models(self) -> None:
        catalog = self._ensure_catalog()
        verified: frozenset[str] = getattr(catalog, "verified", frozenset())

        query = self._search.value.strip() if self._search is not None else ""
        total = len(catalog.providers.get(self._provider, []))

        if self._provider in verified:
            head = (
                f"[#34d399]✓ live[/] [#8a91a8]every model your key can "
                f"use on[/] [#dbe0ee]{escape(self._provider)}[/]"
            )
        else:
            head = f"[#8a91a8]models for[/] [#dbe0ee]{escape(self._provider)}[/]"

        if query:
            head += (
                f"  [#2a3148]·[/]  [{THEME['accent']}]🔍[/] "
                f"[#dbe0ee]{escape(query)}[/]  [#2a3148]·[/]  "
                f"[#565d73]esc to see all {total}[/]"
            )

        self._set_chrome(
            [self._provider],
            foot_key="model",
            search_visible=True,
            steps=self._stepper_for(),
            section=Text.from_markup(head),
        )

    # ─────────────────────────────────────────────
    # 📋 view: saved models
    # ─────────────────────────────────────────────

    def _show_list(self) -> None:
        self._mode = "list"
        self._provider = ""

        assert self._list is not None
        self._list.display = True

        if self._key_box is not None:
            self._key_box.display = False

        self._refresh_view()

        if self._search is not None:
            self._search.focus()  # 🔍 search-first, always ready

    def _render_saved(self) -> None:
        """The saved-model list body (chrome handled by _chrome_list)."""
        self._clear_rows()

        store = ModelStore()

        for model in store.load():
            dead = is_marked_unavailable(model.name)

            if dead and model.is_active:
                dot = "[#fbbf24]⚠[/]"
                suffix = "  [#fbbf24]unavailable — pick another[/]"
            elif dead:
                dot = "[#fbbf24]⚠[/]"
                suffix = "  [#565d73]unavailable[/]"
            elif model.is_active:
                dot = "[#34d399]●[/]"
                suffix = "  [#34d399]active[/]"
            else:
                dot = "[#3a4157]○[/]"
                suffix = ""

            # ⚰️ dead models can't be switched to — they route to the
            #    provider picker with an explanation instead.
            action = self._dead_model_notice(model.name) if dead else self._make_switch(model.name)

            self._mount_row(
                Text.from_markup(
                    f"{dot}  "
                    f"[#dbe0ee]{escape(short_model(model.name))}[/]  "
                    f"[#565d73]{escape(model.name)}[/]"
                    f"{suffix}"
                ),
                action,
            )

        self._mount_row(
            Text.from_markup(
                f"[{THEME['accent']}]➕[/] [#dbe0ee]Add a model…[/]  "
                f"[#565d73]or just search above[/]"
            ),
            self._show_providers,
        )

        self._mount_row(
            Text.from_markup(
                "[#8a91a8]🔄[/] [#dbe0ee]Refresh catalog[/]  "
                "[#565d73]verify against provider APIs[/]"
            ),
            self._refresh,
        )

        self._paint_selection()

    def _dead_model_notice(self, name: str) -> Callable[[], None]:
        def _do() -> None:
            jimmy(self).notify(
                f"⚠ {short_model(name)} is no longer available — choose another",
                timeout=2.5,
            )
            self._show_providers()

        return _do

    def _make_switch(
        self,
        name: str,
    ) -> Callable[[], None]:
        def _do() -> None:
            app = jimmy(self)

            if is_marked_unavailable(name):
                app.notify("⚠ model unavailable — choose another", timeout=2.5)
                self._show_providers()
                return

            try:
                app.switch_model(name)
                self.app.pop_screen()

            except Exception:
                # 🔑 Probably missing API key → key form, esc returns here.
                store = ModelStore()

                cfg = next(
                    (model for model in store.load() if model.name == name),
                    None,
                )

                self._return_mode = "list"
                self._return_provider = ""
                self._prev_query = ""

                if cfg is not None:
                    self._model_name = name
                    self._provider = name.split("/", 1)[0]
                    self._show_key(prefill_env=cfg.api_key_env)
                else:
                    self._show_providers()

        return _do

    # ─────────────────────────────────────────────
    # 🏢 view: provider picker
    # ─────────────────────────────────────────────

    def _show_providers(self) -> None:
        self._mode = "provider"
        self._provider = ""

        assert self._list is not None
        self._list.display = True

        if self._key_box is not None:
            self._key_box.display = False

        self._refresh_view()

        if self._search is not None:
            self._search.focus()

    def _rebuild_providers(
        self,
        query: str = "",
    ) -> None:
        """Provider browse view: legend + ⭐ popular + 🏢 providers.
        With a query, fuzzy-filters providers + cross-searches models."""
        catalog = self._ensure_catalog()

        self._clear_rows()

        q = query.strip().lower()

        providers, models = _search_catalog(
            catalog,
            q,
        )

        verified: frozenset[str] = getattr(catalog, "verified", frozenset())

        # 🏷️ legend chip line above the results (only when unfiltered).
        if not q:
            self._mount_row(
                Text.from_markup(
                    f"[#f5c451]⭐[/] [#8a91a8]popular[/]  [#2a3148]│[/]  "
                    f"[{THEME['accent']}]▸[/] [#8a91a8]providers[/]  "
                    f"[#2a3148]│[/]  [#8a91a8]🔎 matches[/]  "
                    f"[#2a3148]—[/] [#565d73]or search any model above[/]"
                ),
            )

        # ⭐ Popular models first.
        for full in catalog.popular:
            if q and q not in full.lower():
                continue

            provider = full.split("/", 1)[0] if "/" in full else ""

            self._mount_row(
                Text.from_markup(
                    f"[#f5c451]⭐[/] [#dbe0ee]{escape(short_model(full))}[/]  "
                    f"[#565d73]{escape(full)}[/]"
                ),
                lambda f=full, p=provider: self._model_chosen(f, p),
            )

        # 🏢 Providers — model count, key env, ✓ live badge.
        for provider in providers:
            count = len(
                catalog.providers.get(
                    provider,
                    [],
                )
            )

            env = catalog.provider_env_var(provider)

            meta: list[str] = [f"{count} models"]
            if env:
                meta.append(f"🔑 {env}")
            if provider in verified:
                meta.append("[#34d399]✓ live[/]")

            self._mount_row(
                Text.from_markup(
                    f"[{THEME['accent']}]▸[/] "
                    f"[#dbe0ee]{escape(provider)}[/]  "
                    f"[#565d73]{' · '.join(meta)}[/]"
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
                lambda f=full, p=provider: self._model_chosen(f, p),
            )

        if not self._rows:
            self._mount_row(Text.from_markup("[#8a91a8]no match — try another name[/]"))

        self._paint_selection()

    # ─────────────────────────────────────────────
    # 🧠 view: one provider's models (query-scoped)
    # ─────────────────────────────────────────────

    def _show_models(
        self,
        provider: str,
    ) -> None:
        """Enter a provider's view.  If a search query is active it is
        KEPT — the view shows that provider's models filtered by it
        (this is what makes the search row's "showing its N models
        below ↴" promise true).  Esc clears the filter to see all."""
        self._mode = "model"
        self._provider = provider

        assert self._list is not None
        self._list.display = True

        if self._key_box is not None:
            self._key_box.display = False

        self._refresh_view()

        if self._search is not None:
            self._search.focus()

    def _rebuild_models(
        self,
        query: str = "",
    ) -> None:
        """One provider's models.

        No query  → ⭐ popular + 📋 all + ✍️ custom + 🔑 rekey.
        With query → FUZZY-FILTERED, ranked best-first (scoped to this
        provider — the click-through from a search result shows exactly
        the models the search promised), plus ✍️ custom + 🔑 rekey.
        """
        catalog = self._ensure_catalog()

        self._clear_rows()

        q = " ".join(query.strip().lower().split())

        all_models = catalog.providers.get(
            self._provider,
            [],
        )

        popular_here = [
            model
            for model in catalog.popular
            if ("/" in model and model.split("/", 1)[0] == self._provider)
        ]

        # 🔍 scoped fuzzy ranking of THIS provider's models.
        if q:
            compact = q.replace(" ", "")
            ranked: list[tuple[int, str]] = []
            for full in all_models:
                full_l = full.lower()
                short_l = full_l.split("/")[-1] if "/" in full_l else full_l
                s = max(
                    _fuzzy_score(q, full_l),
                    _fuzzy_score(q, short_l),
                    _fuzzy_score(compact, full_l),
                    _fuzzy_score(compact, short_l),
                )
                if s > 0:
                    ranked.append((s, full))
            ranked.sort(key=lambda t: t[0], reverse=True)
            matched = [full for _, full in ranked]

            if self._section is not None:
                self._section.update(
                    Text.from_markup(
                        f"[{THEME['accent']}]🔍[/] "
                        f"[#dbe0ee]{escape(q)}[/]  [#2a3148]·[/]  "
                        f"[#8a91a8]{len(matched)} of {len(all_models)}[/]"
                        f"[#565d73] models in [/]"
                        f"[#dbe0ee]{escape(self._provider)}[/]  "
                        f"[#2a3148]·[/]  [#565d73]esc shows all[/]"
                    )
                )
        else:
            matched = all_models

        entries: list[tuple[Text, Callable[[], None] | None]] = []

        # ⭐ Popular models for this provider (rank matches first).
        for full in popular_here:
            if q and full not in matched:
                continue

            model_name = full.split("/", 1)[-1]

            entries.append(
                (
                    Text.from_markup(
                        f"[#f5c451]⭐[/] [#dbe0ee]{escape(model_name)}[/]  "
                        f"[#565d73]{escape(full)}[/]"
                    ),
                    lambda f=full: self._model_chosen(f, self._provider),
                )
            )

        # 📋 Models — ranked when filtered, alphabetical otherwise.
        for full in matched:
            if full in popular_here:
                continue

            model_name = full.split("/", 1)[-1]

            entries.append(
                (
                    Text.from_markup(
                        f"[#dbe0ee]{escape(model_name)}[/]  [#565d73]{escape(full)}[/]"
                    ),
                    lambda f=full: self._model_chosen(f, self._provider),
                )
            )

        if q and not matched:
            entries.append(
                (
                    Text.from_markup(
                        f"[#8a91a8]no match in {escape(self._provider)} — "
                        f"esc to see all its models[/]"
                    ),
                    None,
                )
            )

        # ✍️ Custom model — with a live preview of the built string.
        typed = q
        if self._provider and typed:
            preview = f"{self._provider}/{typed}"
        elif typed:
            preview = typed
        else:
            preview = "type a name above, then pick this"

        entries.append(
            (
                Text.from_markup(
                    f"[#8a91a8]✍️[/] [#aab2c7]use custom[/]  [#565d73]{escape(preview)}[/]"
                ),
                self._use_custom,
            )
        )

        # 🔑 Explicit "re-enter key" row when a key already exists —
        #    the only way to overwrite it on purpose.
        env_var = catalog.provider_env_var(self._provider)
        if env_var and os.environ.get(env_var):
            entries.append(
                (
                    Text.from_markup(
                        f"[#f5c451]🔑[/] [#aab2c7]re-enter API key for[/] "
                        f"[#dbe0ee]{escape(self._provider)}[/]"
                    ),
                    self._show_key,
                )
            )

        self._render_capped(entries)
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
            provider = typed.split("/", 1)[0]
        else:
            provider = self._provider
            full = f"{provider}/{typed}" if provider else typed

        self._model_chosen(full, provider)

    # ─────────────────────────────────────────────
    # 🔍 view: global search overlay (saved-list mode)
    # ─────────────────────────────────────────────

    def _render_search(self, query: str) -> None:
        """GLOBAL smart results (shown from the saved-list view):

        ▸ providers (with "showing its N models below ↴" — clicking
        opens that provider SCOPED to the query) · ⭐ popular · 🔎
        fuzzy model matches · ✍️ custom.

        Fuzzy: "glm flash" finds "glm-4.6-flash".  Model names always
        render via short_model() so nested ids stay readable."""
        catalog = self._ensure_catalog()

        q = query.strip().lower()

        providers, models = _search_catalog(
            catalog,
            query,
        )

        verified: frozenset[str] = getattr(catalog, "verified", frozenset())

        if self._crumb is not None:
            self._crumb.update(_crumb(["Models", f'🔍 "{query.strip()}"']))

        if self._steps is not None:
            self._steps.update(self._stepper_for())

        if self._foot is not None:
            self._foot.update(Text.from_markup(f"[#565d73]{_FOOT.get('search', '')}[/]"))

        if self._section is not None:
            total = len(providers) + len(models)
            self._section.update(
                Text.from_markup(
                    f"[{THEME['accent']}]🔍[/] [#dbe0ee]{escape(query.strip())}[/]  "
                    f"[#2a3148]·[/]  [#8a91a8]{total} matches[/]  "
                    f"[#2a3148]·[/]  [#565d73]fuzzy — spaces & dashes don't matter[/]"
                )
            )

        self._clear_rows()

        # 🧺 collect first, render capped — never mount thousands of rows.
        entries: list[tuple[Text, Callable[[], None] | None]] = []

        # 📊 how many of each provider's models actually matched — used
        #    for the honest "showing its N models below" hint.
        matched_per_provider: dict[str, int] = {}
        for full in models:
            p = full.split("/", 1)[0] if "/" in full else ""
            matched_per_provider[p] = matched_per_provider.get(p, 0) + 1

        # ▸ Providers FIRST — clicking opens the provider SCOPED to the
        #   query, so the hint is a promise, not a tease.
        for provider in providers:
            count = len(catalog.providers.get(provider, []))
            env = catalog.provider_env_var(provider)

            meta: list[str] = [f"{count} models"]
            if env:
                meta.append(f"🔑 {env}")
            if provider in verified:
                meta.append("[#34d399]✓ live[/]")

            followed = matched_per_provider.get(provider, 0)
            if followed:
                hint = (
                    f"  [#2a3148]—[/] [#565d73]↵ shows its "
                    f"{min(followed, _MAX_RESULTS)} matched models[/]"
                )
            else:
                hint = f"  [#2a3148]—[/] [#565d73]↵ browse all {count} models[/]"

            entries.append(
                (
                    Text.from_markup(
                        f"[{THEME['accent']}]▸[/] "
                        f"[#dbe0ee]{escape(provider)}[/]  "
                        f"[#565d73]{' · '.join(meta)}[/]{hint}"
                    ),
                    lambda p=provider: self._show_models(p),
                )
            )

        # ⭐ Popular matches (fuzzy-aware).
        for full in catalog.popular:
            if _fuzzy_score(q, full.lower()) > 0:
                provider = full.split("/", 1)[0] if "/" in full else ""

                entries.append(
                    (
                        Text.from_markup(
                            f"[#f5c451]⭐[/] [#dbe0ee]{escape(short_model(full))}[/]  "
                            f"[#565d73]{escape(full)}[/]"
                        ),
                        lambda f=full, p=provider: self._model_chosen(f, p),
                    )
                )

        # 🔎 Fuzzy model matches — correct readable names, deduped.
        seen: set[str] = set()
        for full in models:
            if full in seen or full in catalog.popular:
                continue
            seen.add(full)

            provider = full.split("/", 1)[0] if "/" in full else ""

            entries.append(
                (
                    Text.from_markup(
                        f"[#dbe0ee]{escape(short_model(full))}[/]  [#565d73]{escape(full)}[/]"
                    ),
                    lambda f=full, p=provider: self._model_chosen(f, p),
                )
            )

        # ✍️ Custom row.
        typed = query.strip()
        if "/" in typed:
            entries.append(
                (
                    Text.from_markup(
                        f"[#8a91a8]✍️[/] [#aab2c7]use custom[/]  [#565d73]{escape(typed)}[/]"
                    ),
                    self._use_custom,
                )
            )
        elif self._provider:
            entries.append(
                (
                    Text.from_markup(
                        f"[#8a91a8]✍️[/] [#aab2c7]use custom[/]  "
                        f"[#565d73]{escape(self._provider + '/' + typed)}[/]"
                    ),
                    self._use_custom,
                )
            )
        else:
            entries.append(
                (
                    Text.from_markup(
                        "[#8a91a8]✍️[/] [#565d73]type provider/model "
                        "(e.g. openai/gpt-4o) for a custom entry[/]"
                    ),
                    None,
                )
            )

        if not entries:
            entries.append(
                (
                    Text.from_markup("[#8a91a8]no match — try another name[/]"),
                    None,
                )
            )

        self._render_capped(entries)
        self._paint_selection()

    # ─────────────────────────────────────────────
    # 🎯 model chosen — the SAME-API fast path
    # ─────────────────────────────────────────────

    def _model_chosen(
        self,
        full: str,
        provider: str,
    ) -> None:
        """A model was picked.

        🔑 Key already set (or provider needs none) → save & switch
        INSTANTLY, no key screen.  Missing key → paste-key form, and
        esc from the form restores the exact search/view you came from.
        """
        # ↩️ remember where we are so the key form can return here.
        self._return_mode = self._mode
        self._return_provider = self._provider
        self._prev_query = self._search.value if self._search is not None else ""

        self._model_name = full
        self._provider = provider

        catalog = self._ensure_catalog()
        env_var = catalog.provider_env_var(provider)

        if env_var and not os.environ.get(env_var):
            self._show_key()
            return

        # ✅ key present / not needed → instant switch
        self._save()

    # ─────────────────────────────────────────────
    # 🔑 API key
    # ─────────────────────────────────────────────

    def _show_key(
        self,
        prefill_env: str = "",
    ) -> None:
        self._mode = "key"

        assert self._list is not None
        self._list.display = False

        if self._key_box is not None:
            self._key_box.display = True

        # Search box hides but KEEPS its value — esc restores it.
        if self._search is not None:
            self._search.display = False

        if self._crumb is not None:
            self._crumb.update(_crumb(["Models", self._provider or "model", "key"]))

        if self._steps is not None:
            self._steps.update(self._stepper_for())

        if self._foot is not None:
            self._foot.update(Text.from_markup(f"[#565d73]{_FOOT.get('key', '')}[/]"))

        catalog = self._ensure_catalog()

        env_var = prefill_env or catalog.provider_env_var(self._provider)

        api_base = catalog.provider_api_base(self._provider)

        fullname = self.query_one("#model-fullname", Static)

        fullname.update(
            Text.from_markup(
                f"[{THEME['accent']}]◈[/] "
                f"[#e2e6f2]{escape(short_model(self._model_name))}[/]  "
                f"[#565d73]{escape(self._model_name)}[/]"
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
                        f"[#f5c451]{escape(env_var)}[/] "
                        f"{already}"
                    )
                )

        msg = self.query_one("#model-form-msg", Static)

        if api_base:
            msg.update(Text.from_markup(f"[#565d73]🌐 endpoint: {escape(api_base)}[/]"))
        else:
            msg.update("")

        if self._in_key is not None:
            self._in_key.value = ""
            self._in_key.focus()

    def _leave_key(self) -> None:
        """↩️ Return from the key form to the exact view/search the user
        came from (search text restored, results re-rendered)."""
        self._mode = self._return_mode
        self._provider = self._return_provider

        if self._key_box is not None:
            self._key_box.display = False

        if self._search is not None:
            self._search.value = self._prev_query
            self._search.display = True

        self._prev_query = ""

        assert self._list is not None
        self._list.display = True

        self._refresh_view()

        if self._search is not None:
            self._search.focus()

    # ─────────────────────────────────────────────
    # 💾 save
    # ─────────────────────────────────────────────

    def _save(self) -> None:
        """💾 Validate → save/update config → activate → hot-swap.

        Called BOTH from the key form (↵ / 💾) and from the instant
        same-API fast path — so failures surface via notify too (the
        form may be hidden when auto-switching).
        """

        app = jimmy(self)

        # ✅ Validate model selection FIRST.
        # This must happen before using provider.
        name = self._model_name.strip()

        msg = self.query_one("#model-form-msg", Static)

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
            save_key_to_env(env_var, key)

        # 🔐 Provider needs a key, but we don't have one.
        elif env_var and not os.environ.get(env_var):
            message = f"✕ paste the key (or set {env_var} in ~/.jimmy/.env)"
            msg.update(Text.from_markup(f"[#fb7185]{escape(message)}[/]"))
            self.notify(f"⚠ {message}", severity="warning", timeout=2.5)
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
            text = str(exc)[:160]
            msg.update(Text.from_markup(f"[#fb7185]✕ {escape(text)}[/]"))
            self.notify(f"⚠ {text}", severity="error", timeout=2.5)
            return

        self.app.pop_screen()

    # ─────────────────────────────────────────────
    # 🔄 catalog refresh (network OFF the render loop)
    # ─────────────────────────────────────────────

    def _refresh(self) -> None:
        """🔄 Force fresh discovery — live provider APIs in a thread."""

        self.notify("🌐 refreshing catalog…", timeout=1.5)

        async def _work() -> None:
            try:
                catalog = await asyncio.to_thread(
                    get_catalog,
                    force=True,
                    live=True,
                )
            except Exception as exc:
                self.notify(
                    f"🌐 refresh failed: {escape(str(exc))}",
                    severity="error",
                    timeout=2.5,
                )
                return

            self._catalog = catalog

            try:
                self._refresh_view()
            except Exception:
                pass  # screen may have closed mid-refresh

            self.notify("🌐 catalog refreshed", timeout=1.5)

        self.run_worker(
            _work(),
            name="catalog-refresh",
            group="catalog-refresh",
            exclusive=True,
            exit_on_error=False,
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

        # 🔍 every keystroke re-renders the MODE-AWARE view — global
        #    search on the saved list, scoped filtering inside a provider.
        self._refresh_view()

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

        eye = self.query_one("#model-eye", Static)

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
        """esc, in order: key → back · active filter → clear it (shows
        the full level you're on) · provider models → providers ·
        providers → list · list → close."""

        if self._mode == "key":
            self._leave_key()
            return

        if self._search is not None and self._search.value.strip():
            self._search.value = ""
            self._refresh_view()
            if self._search is not None:
                self._search.focus()
            return

        if self._mode == "provider":
            self._show_list()
            return

        if self._mode == "model":
            self._show_providers()
            return

        self.app.pop_screen()
