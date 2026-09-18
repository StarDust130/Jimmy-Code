"""🧪 Live catalog: structure, popular verification, env vars, cache."""

from jimmy.llm.catalog import get_catalog


def test_catalog_has_providers_and_models():
    cat = get_catalog()
    assert cat.providers  # 🌐 live registry non-empty
    assert any(m.startswith("openai/") for m in cat.providers.get("openai", []))


def test_popular_only_contains_real_models():
    cat = get_catalog()
    everything = {m for ms in cat.providers.values() for m in ms}
    assert all(p in everything for p in cat.popular)  # ⭐ no dead entries


def test_env_var_convention_and_overrides():
    cat = get_catalog()
    assert cat.provider_env_var("someprovider") == "SOMEPROVIDER_API_KEY"
    assert cat.provider_env_var("openai") == "OPENAI_API_KEY"
    assert cat.provider_env_var("ollama") == ""


def test_cache_roundtrip(tmp_path, monkeypatch):
    from jimmy.llm import catalog

    monkeypatch.setattr(catalog, "CACHE_FILE", tmp_path / "c.json")
    first = get_catalog()
    cached = catalog._load_cache()
    assert cached is not None and cached["providers"] == first.providers
