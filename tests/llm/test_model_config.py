"""🧪 Model store + factory."""

import pytest

from jimmy.llm.model_config import ModelConfig, ModelStore, default_models
from jimmy.llm.provider_factory import MissingAPIKeyError, create_provider


@pytest.fixture
def store(tmp_path):
    return ModelStore(path=tmp_path / "models.json")


def test_load_returns_default_when_no_file(store):
    models = store.load()
    assert models == default_models()
    assert models[0].is_active


def test_add_and_set_active(store):
    store.add(ModelConfig(name="openai/gpt-4o", api_key_env="OPENAI_API_KEY"))
    store.set_active("openai/gpt-4o")

    assert store.active().name == "openai/gpt-4o"

    # 💾 persisted to disk
    fresh = ModelStore(path=store.path)
    assert fresh.active().name == "openai/gpt-4o"


def test_add_duplicate_raises(store):
    with pytest.raises(ValueError):
        store.add(ModelConfig(name=default_models()[0].name))


def test_cannot_remove_default(store):
    with pytest.raises(ValueError):
        store.remove(default_models()[0].name)


def test_remove_active_falls_back_to_default(store):
    store.add(ModelConfig(name="openai/gpt-4o", api_key_env="OPENAI_API_KEY"))
    store.set_active("openai/gpt-4o")
    store.remove("openai/gpt-4o")

    assert store.active().name == default_models()[0].name


def test_set_active_unknown_raises(store):
    with pytest.raises(ValueError):
        store.set_active("nope/whatever")


def test_exactly_one_active_enforced(store):
    store.add(ModelConfig(name="openai/gpt-4o", api_key_env="OPENAI_API_KEY"))
    store.set_active("openai/gpt-4o")

    actives = [m for m in store.load() if m.is_active]
    assert len(actives) == 1


def test_factory_requires_api_key(monkeypatch):
    monkeypatch.delenv("FAKE_KEY_ENV", raising=False)

    with pytest.raises(MissingAPIKeyError):
        create_provider(ModelConfig(name="openai/gpt-4o", api_key_env="FAKE_KEY_ENV"))


def test_factory_builds_with_key(monkeypatch):
    monkeypatch.setenv("FAKE_KEY_ENV", "sk-test")

    provider = create_provider(
        ModelConfig(
            name="openai/gpt-4o",
            api_key_env="FAKE_KEY_ENV",
            api_base="https://api.example.com/v1",  # 🌐 z.ai style
        )
    )

    assert provider.model == "openai/gpt-4o"
    assert provider.api_base == "https://api.example.com/v1"
