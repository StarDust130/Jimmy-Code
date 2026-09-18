"""Catalog tests: stale/deprecated models, live verification, cache TTLs,
unavailable marking, Ollama merge.  No real network, no real HOME writes."""

from __future__ import annotations

import json
import time

import pytest

from jimmy.llm import catalog
from jimmy.llm.catalog import (
    get_catalog,
    is_marked_unavailable,
    is_model_not_found,
    mark_unavailable,
)

# 🔑 Capture the REAL registry fetcher at import time — the autouse
#    `isolated_catalog` fixture stubs catalog._from_litellm during every
#    test; tests that exercise the actual litellm path restore this.
_REAL_FROM_LITELLM = catalog._from_litellm


@pytest.fixture(autouse=True)
def isolated_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """No real HOME writes, no real network, no real Ollama."""
    monkeypatch.setattr(catalog, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(catalog, "UNAVAILABLE_FILE", tmp_path / "dead.json")
    monkeypatch.setattr(catalog, "_fetch_ollama", lambda: [])
    monkeypatch.setattr(catalog, "_LIVE_ENDPOINTS", {})
    monkeypatch.setattr(
        catalog,
        "_from_litellm",
        lambda: {
            "groq": ["groq/llama-3.3-70b-versatile", "groq/retired-model"],
            "openai": ["openai/gpt-4o"],
        },
    )


def _write_cache(payload: dict) -> None:
    catalog.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    catalog.CACHE_FILE.write_text(json.dumps(payload))


# ── registry ───────────────────────────────────────────────────────────


def test_registry_models_sorted_and_prefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    import litellm

    # Undo the autouse fixture's stub — this test verifies the REAL
    # registry path (normalize to provider/model, dedupe, sort).
    monkeypatch.setattr(catalog, "_from_litellm", _REAL_FROM_LITELLM)

    monkeypatch.setattr(
        litellm,
        "models_by_provider",
        {"groq": ["b-model", "a-model"], "openai": ["gpt-4o", "openai/gpt-4o"]},
        raising=False,
    )
    out = catalog._from_litellm()
    assert out["groq"] == ["groq/a-model", "groq/b-model"]
    assert out["openai"] == ["openai/gpt-4o"]  # dedup, no double prefix


# ── popular verification ───────────────────────────────────────────────


def test_popular_drops_models_not_in_registry() -> None:
    cat = get_catalog()
    everything = {m for ms in cat.providers.values() for m in ms}
    assert "groq/llama-3.3-70b-versatile" in cat.popular
    assert all(p in everything for p in cat.popular)  # dead ones can't show


# ── registry cache TTL ─────────────────────────────────────────────────


def test_fresh_cache_is_used_without_refetch() -> None:
    _write_cache(
        {
            "fetched_at": time.time(),
            "providers": {"zzz": ["zzz/only"]},
            "live": {},
        }
    )
    cat = get_catalog()
    assert cat.providers == {"zzz": ["zzz/only"]}


def test_stale_registry_cache_is_refreshed() -> None:
    _write_cache(
        {
            "fetched_at": time.time() - catalog.CACHE_TTL - 10,
            "providers": {"old": ["old/dead"]},
            "live": {},
        }
    )
    cat = get_catalog()
    assert "old" not in cat.providers
    assert "groq/llama-3.3-70b-versatile" in cat.providers["groq"]


# ── live provider verification ─────────────────────────────────────────


def test_live_fetch_intersects_and_adds_new(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        catalog,
        "_LIVE_ENDPOINTS",
        {"groq": {"url": "https://x/models", "env": "GROQ_API_KEY"}},
    )
    monkeypatch.setattr(
        catalog,
        "_fetch_live_models",
        lambda p: ["llama-3.3-70b-versatile", "brand-new"],
    )
    cat = get_catalog(force=True, live=True)
    # retired dropped, live-only (new release) added
    assert cat.providers["groq"] == [
        "groq/brand-new",
        "groq/llama-3.3-70b-versatile",
    ]
    assert "groq/retired-model" not in cat.providers["groq"]


def test_live_fetch_failure_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        catalog,
        "_LIVE_ENDPOINTS",
        {"groq": {"url": "https://x/models", "env": "GROQ_API_KEY"}},
    )
    monkeypatch.setattr(catalog, "_fetch_live_models", lambda p: None)
    cat = get_catalog(force=True, live=True)
    # provider API unreachable → registry stands, nothing crashes
    assert "groq/retired-model" in cat.providers["groq"]
    assert "groq/llama-3.3-70b-versatile" in cat.providers["groq"]


def test_stale_live_cache_is_not_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        catalog,
        "_LIVE_ENDPOINTS",
        {"groq": {"url": "https://x/models", "env": "GROQ_API_KEY"}},
    )
    now = time.time()
    _write_cache(
        {
            "fetched_at": now,
            "providers": {"groq": ["groq/llama-3.3-70b-versatile", "groq/retired-model"]},
            "live": {
                "groq": {
                    "fetched_at": now - catalog.LIVE_TTL - 5,
                    "models": ["llama-3.3-70b-versatile"],
                }
            },
        }
    )
    cat = get_catalog()  # cache path only — stale live data must be ignored
    assert "groq/retired-model" in cat.providers["groq"]


def test_fresh_live_cache_filters_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        catalog,
        "_LIVE_ENDPOINTS",
        {"groq": {"url": "https://x/models", "env": "GROQ_API_KEY"}},
    )
    now = time.time()
    _write_cache(
        {
            "fetched_at": now,
            "providers": {"groq": ["groq/llama-3.3-70b-versatile", "groq/retired-model"]},
            "live": {
                "groq": {
                    "fetched_at": now - 10,
                    "models": ["llama-3.3-70b-versatile"],
                }
            },
        }
    )

    def _boom(p: str) -> list[str]:
        raise AssertionError("network hit on cached path")

    monkeypatch.setattr(catalog, "_fetch_live_models", _boom)
    cat = get_catalog()
    assert cat.providers["groq"] == ["groq/llama-3.3-70b-versatile"]


# ── unavailable marking (the 404 loop) ─────────────────────────────────


def test_mark_unavailable_removes_from_catalog() -> None:
    mark_unavailable("openai/gpt-4o", "404 model_not_found")
    assert is_marked_unavailable("openai/gpt-4o")
    cat = get_catalog(force=True)
    assert "openai/gpt-4o" not in cat.providers.get("openai", [])
    # other providers unaffected
    assert "groq/llama-3.3-70b-versatile" in cat.providers["groq"]


def test_unavailable_marked_persisted_to_disk() -> None:
    mark_unavailable("x/dead", "404")
    raw = json.loads(catalog.UNAVAILABLE_FILE.read_text())
    assert "x/dead" in raw


# ── ollama ─────────────────────────────────────────────────────────────


def test_ollama_local_models_still_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "_fetch_ollama", lambda: ["ollama/qwen3-coder:8b"])
    cat = get_catalog(force=True)
    assert "ollama/qwen3-coder:8b" in cat.providers["ollama"]


# ── 404 detection ──────────────────────────────────────────────────────


def test_is_model_not_found_detection() -> None:
    err = RuntimeError("Error code: 404 - model_not_found")
    err.status_code = 404  # type: ignore[attr-defined]
    assert is_model_not_found(err) is True

    class NotFound(RuntimeError):
        status_code = 404

    assert is_model_not_found(NotFound("The model does not exist")) is True
    assert is_model_not_found(RuntimeError("connection reset")) is False
    assert is_model_not_found(RuntimeError("401 unauthorized")) is False
