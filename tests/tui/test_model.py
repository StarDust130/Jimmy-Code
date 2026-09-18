"""🧪 TUI model picker: store wiring, provider switching, and UI flow."""

from __future__ import annotations

from typing import cast

import pytest

from jimmy.llm.model_config import (
    ModelConfig,
    ModelStore,
    default_models,
)
from jimmy.llm.provider import LLMProvider
from jimmy.llm.provider_factory import MissingAPIKeyError

# ─────────────────────────────────────────────
# 💾 ModelStore
# ─────────────────────────────────────────────


def test_store_default_active(tmp_path):
    """🌟 Fresh install → built-in default is active."""
    store = ModelStore(path=tmp_path / "models.json")

    active = store.active()

    assert active.name == default_models()[0].name
    assert active.is_active
    assert "gemini" in active.name.lower()


def test_store_add_switch_persist(tmp_path):
    """💾 Add + switch survives a fresh store load."""
    path = tmp_path / "models.json"
    store = ModelStore(path=path)

    store.add(
        ModelConfig(
            name="openai/gpt-4o",
            api_key_env="OPENAI_API_KEY",
        )
    )

    store.set_active("openai/gpt-4o")

    fresh = ModelStore(path=path)

    assert fresh.active().name == "openai/gpt-4o"

    names = [model.name for model in fresh.load()]

    assert default_models()[0].name in names
    assert "openai/gpt-4o" in names


def test_store_switch_unknown_raises(tmp_path):
    """🚫 Unknown model cannot become active."""
    store = ModelStore(path=tmp_path / "models.json")

    with pytest.raises(ValueError):
        store.set_active("nope/never")


def test_store_remove_active_falls_back(tmp_path):
    """🛟 Removing the active model → built-in default returns."""
    store = ModelStore(path=tmp_path / "models.json")

    default_name = default_models()[0].name

    store.add(
        ModelConfig(
            name="openai/gpt-4o",
            api_key_env="OPENAI_API_KEY",
        )
    )

    store.set_active("openai/gpt-4o")
    store.remove("openai/gpt-4o")

    assert store.active().name == default_name


# ─────────────────────────────────────────────
# 🏭 Provider factory
# ─────────────────────────────────────────────


def test_factory_missing_key_raises(monkeypatch):
    """🔑 Missing env var → clear error."""
    monkeypatch.delenv(
        "TEST_NOPE_KEY",
        raising=False,
    )

    from jimmy.llm.provider_factory import create_provider

    with pytest.raises(MissingAPIKeyError):
        create_provider(
            ModelConfig(
                name="openai/gpt-4o",
                api_key_env="TEST_NOPE_KEY",
            )
        )


def test_factory_builds_provider(monkeypatch):
    """🏭 Provider is built correctly from ModelConfig."""
    monkeypatch.setenv(
        "TEST_OK_KEY",
        "sk-fake",
    )

    from jimmy.llm.provider_factory import create_provider

    provider = create_provider(
        ModelConfig(
            name="openai/gpt-4o",
            api_key_env="TEST_OK_KEY",
            api_base="https://api.test/v1",
        )
    )

    assert provider.model == "openai/gpt-4o"
    assert provider.api_key == "sk-fake"
    assert provider.api_base == "https://api.test/v1"


# ─────────────────────────────────────────────
# 🤖 Agent hot-swap
# ─────────────────────────────────────────────


def test_agent_set_provider_swaps_and_keeps_history():
    """🔁 Provider changes without losing agent history."""

    from jimmy.agent import Agent
    from jimmy.context.builder import ContextBuilder
    from jimmy.llm.types import Message

    class P1:
        model = "one"

    class P2:
        model = "two"

    # These fake providers are never called in this test.
    # The cast tells Pylance that they intentionally stand in
    # for LLMProvider instances.
    provider1 = cast(
        LLMProvider,
        P1(),
    )

    provider2 = cast(
        LLMProvider,
        P2(),
    )

    agent = Agent(
        provider1,
        context=ContextBuilder(),
    )

    agent.history.append(
        Message(
            role="user",
            content="old",
        )
    )

    agent.set_provider(provider2)

    assert agent.provider.model == "two"
    assert agent.history[-1].content == "old"


# ─────────────────────────────────────────────
# 🖥️ ModelScreen test app
# ─────────────────────────────────────────────


async def _pilot_model_screen(
    monkeypatch,
    tmp_path,
):
    """Boot the real TUI with an isolated temporary model store."""

    from jimmy.llm.litellm_provider import LiteLLMProvider
    from tui.app import JimmyApp

    monkeypatch.setenv(
        "GEMINI_API_KEY",
        "fake-for-test",
    )

    # 💾 Every ModelStore in this test uses the same temp file.
    monkeypatch.setattr(
        "jimmy.llm.model_config.ModelStore.__init__",
        lambda self, path=None: setattr(
            self,
            "path",
            tmp_path / "models.json",
        ),
    )

    app = JimmyApp(
        provider=LiteLLMProvider(
            model="gemini/gemini-3.5-flash-lite",
            api_key="fake",
        )
    )

    async with app.run_test() as pilot:
        from tui.screens.models import ModelScreen

        app.push_screen(ModelScreen())

        await pilot.pause()
        await pilot.pause()

        assert isinstance(
            app.screen,
            ModelScreen,
        )

        yield app, pilot


# ─────────────────────────────────────────────
# 📋 ModelScreen list
# ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_screen_shows_saved_models(
    monkeypatch,
    tmp_path,
):
    """📋 List shows saved models plus the add row."""

    gen = _pilot_model_screen(
        monkeypatch,
        tmp_path,
    )

    app, pilot = await gen.__anext__()

    try:
        from tui.screens.models import ModelScreen

        assert isinstance(
            app.screen,
            ModelScreen,
        )

        rows = list(app.screen.query(".model-row"))

        # 🌟 One built-in default + one Add row.
        assert len(rows) >= 2

    finally:
        await gen.aclose()


# ─────────────────────────────────────────────
# ❌ Invalid add
# ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_screen_add_rejects_bad_name(
    monkeypatch,
    tmp_path,
):
    """➕ No model selected → inline error, screen stays open."""

    gen = _pilot_model_screen(
        monkeypatch,
        tmp_path,
    )

    app, pilot = await gen.__anext__()

    try:
        from tui.screens.models import ModelScreen

        screen = app.screen

        assert isinstance(
            screen,
            ModelScreen,
        )

        # Enter the existing provider/model wizard.
        screen._show_providers()

        # Simulate no model being selected.
        screen._model_name = ""
        screen._provider = None

        # Attempt save.
        screen._save()

        await pilot.pause()

        # Validation should fail, so modal stays open.
        assert isinstance(
            app.screen,
            ModelScreen,
        )

    finally:
        await gen.aclose()


# ─────────────────────────────────────────────
# 🔄 App model switching
# ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_switch_model_persists_and_swaps(
    monkeypatch,
    tmp_path,
):
    """🔄 switch_model → provider changes and persistence survives."""

    gen = _pilot_model_screen(
        monkeypatch,
        tmp_path,
    )

    app, pilot = await gen.__anext__()

    try:
        app.model_store.add(
            ModelConfig(
                name="openai/gpt-4o",
                api_key_env="TEST_UI_KEY",
            )
        )

        monkeypatch.setenv(
            "TEST_UI_KEY",
            "sk-fake",
        )

        app.switch_model("openai/gpt-4o")

        await pilot.pause()

        # 🤖 Agent uses new model.
        assert app.agent.provider.model == "openai/gpt-4o"

        # 💾 New model is persisted as active.
        fresh = ModelStore(path=app.model_store.path)

        assert fresh.active().name == "openai/gpt-4o"

        # 🏷️ Navbar was updated too.
        assert "gpt-4o" in app.top_bar.model_name

    finally:
        await gen.aclose()
