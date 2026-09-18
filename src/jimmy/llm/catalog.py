"""🌐 Live model catalog — dynamic discovery, no hard-coded model list.

Sources:
  • LiteLLM's registry (litellm.models_by_provider) → every provider/model
    LiteLLM knows, including newly released models
  • Ollama /api/tags → local models, discoverable when Ollama is running
  • ⭐ popular list → curated litellm strings, but each is VERIFIED against
    the live registry (retired models disappear automatically)

Caching:
  💾 ~/.jimmy/catalog_cache.json · 6h TTL · get_catalog(force=True) refreshes
  Ollama is re-probed on every call (cheap, and local models come/go).
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CACHE_FILE = Path.home() / ".jimmy" / "catalog_cache.json"
CACHE_TTL = 6 * 60 * 60  # ⏱️ 6 hours
OLLAMA_URL = "http://localhost:11434/api/tags"
OLLAMA_TIMEOUT = 0.6  # ⚡ seconds — local probe must never slow the UI

# ⭐ curated popular models (litellm strings) — verified against the
#    registry before display, so this list can never show dead models
POPULAR: tuple[str, ...] = (
    "anthropic/claude-sonnet-4-5",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "gemini/gemini-2.5-pro",
    "gemini/gemini-2.5-flash",
    "openrouter/z-ai/glm-4.6",
    "deepseek/deepseek-chat",
    "groq/llama-3.3-70b-versatile",
)

# 🔑 env-var names that don't follow the <PROVIDER>_API_KEY convention
ENV_VAR_OVERRIDES: dict[str, str] = {
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
    "vertex_ai": "GOOGLE_APPLICATION_CREDENTIALS",
    "azure": "AZURE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "z.ai": "ZAI_API_KEY",
    "ollama": "",  # 🟢 local — no key
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "xai": "XAI_API_KEY",
    "cohere": "COHERE_API_KEY",
    "together_ai": "TOGETHERAI_API_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
}

# 🌐 providers needing a custom endpoint
API_BASE_OVERRIDES: dict[str, str] = {
    "ollama": "http://localhost:11434",
}


@dataclass(frozen=True, slots=True)
class Catalog:
    """Snapshot of all discoverable providers → models."""

    providers: dict[str, list[str]]  # 📦 provider → litellm model strings
    popular: list[str]  # ⭐ verified popular models
    fetched_at: float  # ⏱️ epoch of the registry fetch

    def provider_env_var(self, provider: str) -> str:
        """🔑 API-key env var for a provider (convention + overrides)."""
        if provider in ENV_VAR_OVERRIDES:
            return ENV_VAR_OVERRIDES[provider]
        return f"{provider.upper().replace('-', '_')}_API_KEY"

    def provider_api_base(self, provider: str) -> str:
        """🌐 custom endpoint for a provider ('' = none)."""
        return API_BASE_OVERRIDES.get(provider, "")


# ─────────────────────────────────────
# 🦙 Ollama (local) discovery
# ─────────────────────────────────────


def _fetch_ollama() -> list[str]:
    """Ask local Ollama what models it has. Fast-fail if not running."""
    try:
        with urllib.request.urlopen(OLLAMA_URL, timeout=OLLAMA_TIMEOUT) as r:
            data = json.loads(r.read().decode())
        return [f"ollama/{m['name']}" for m in data.get("models", [])]
    except Exception:
        return []  # 🤷 no Ollama → silently skipped


# ─────────────────────────────────────
# 🏭 registry fetch + cache
# ─────────────────────────────────────


def _from_litellm() -> dict[str, list[str]]:
    """Pull provider → [litellm model strings] from LiteLLM's registry."""
    import litellm

    raw = getattr(litellm, "models_by_provider", None) or {}
    providers: dict[str, list[str]] = {}

    for provider, models in raw.items():
        key = str(provider).strip().lower()
        if not key:
            continue
        cleaned: list[str] = []
        for m in models:
            name = str(m).strip()
            if not name:
                continue
            # 🏷️ normalize to full litellm strings: provider/model
            cleaned.append(name if "/" in name else f"{key}/{name}")
        if cleaned:
            providers[key] = sorted(set(cleaned))

    return providers


def _load_cache() -> dict | None:
    try:
        return json.loads(CACHE_FILE.read_text())
    except Exception:
        return None


def _save_cache(providers: dict[str, list[str]], fetched_at: float) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({"fetched_at": fetched_at, "providers": providers}))
    except Exception:
        pass  # 💾 cache write failure is never fatal


def get_catalog(*, force: bool = False) -> Catalog:
    """🌐 Get the live catalog — cached when fresh, refreshed when asked.

    force=True → re-pull from LiteLLM's registry (the TUI binds this
    to a 🔄 refresh action so users can see brand-new models instantly).
    Ollama is ALWAYS probed fresh (fast, and local state changes often).
    """
    now = time.time()

    if not force:
        cached = _load_cache()
        if cached and now - cached.get("fetched_at", 0) < CACHE_TTL:
            providers = cached.get("providers", {})
        else:
            providers = {}
    else:
        providers = {}

    if not providers:  # 🏗️ cache miss / stale / forced
        providers = _from_litellm()
        if providers:  # 🛟 only cache a real fetch, keep fallback intact
            _save_cache(providers, now)
        else:
            cached = _load_cache()
            providers = (cached or {}).get("providers", {})

    # 🦙 local models merge in fresh every time
    ollama = _fetch_ollama()
    if ollama:
        existing = set(providers.get("ollama", []))
        providers["ollama"] = sorted(existing | set(ollama))

    return Catalog(
        providers=providers,
        popular=_verified_popular(providers),
        fetched_at=now,
    )


def _verified_popular(providers: dict[str, list[str]]) -> list[str]:
    """⭐ keep only popular entries that actually exist in the registry."""
    everything = {m for models in providers.values() for m in models}
    return [p for p in POPULAR if p in everything]


def search(catalog: Catalog, query: str) -> tuple[list[str], list[str]]:
    """🔍 Search across providers AND models in one query.

    Returns (matching_providers, matching_models) — models is a flat
    list of litellm strings whose name or provider matches.
    """
    q = query.strip().lower()
    if not q:
        return list(catalog.providers), []

    providers = [p for p in catalog.providers if q in p.lower()]
    models = [m for models in catalog.providers.values() for m in models if q in m.lower()]
    return providers, sorted(set(models))


# ─────────────────────────────────────
# 💾 API key persistence (~/.jimmy/.env)
# ─────────────────────────────────────

ENV_FILE = Path.home() / ".jimmy" / ".env"


def save_key_to_env(env_var: str, key: str) -> None:
    """💾 Persist a pasted API key to ~/.jimmy/.env (never in models.json)."""
    import os

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    if ENV_FILE.exists():
        lines = [
            line
            for line in ENV_FILE.read_text().splitlines()
            if line.strip() and not line.startswith(f"{env_var}=")
        ]
    lines.append(f"{env_var}={key}")
    ENV_FILE.write_text("\n".join(lines) + "\n")

    os.environ[env_var] = key  # ✅ live immediately, no restart
