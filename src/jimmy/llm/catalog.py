"""🌐 Live model catalog — dynamic discovery, never trusting one source.

Trust order per provider:
  1. Provider models/list API (Groq, OpenAI, DeepSeek, Mistral, xAI,
     OpenRouter, Anthropic) queried with the user's own API key —
     authoritative: the catalog is INTERSECTED with it, so retired
     models disappear immediately and brand-new ones appear without
     changing this file.
  2. LiteLLM registry — base source for every other provider.
  3. Ollama /api/tags — local models, probed fresh on every call.

Search:
  🔍 smart_search() — substring AND fuzzy subsequence matching with
  scoring, so "glm flash", "gpt4o", "csonnet" all find the right
  models; results come back best-ranked first.

Unavailable tracking (the 404 loop):
  When a saved model dies (404 / model_not_found at request time), the
  TUI calls mark_unavailable().  get_catalog() then excludes it from
  every list and from ⭐ popular, so users are guided to another model
  instead of hitting the same dead one again.

Caching — performance only, NEVER authoritative:
  💾 ~/.jimmy/catalog_cache.json
     registry: 6h TTL · per-provider live lists: 1h TTL
     * stale registry → refetched
     * stale live data is simply NOT applied (fail open to registry)
     * live=True (the 🔄 refresh) re-queries provider APIs IN PARALLEL
       with bounded timeouts — the TUI runs this off the render loop
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

CACHE_FILE = Path.home() / ".jimmy" / "catalog_cache.json"
CACHE_TTL = 6 * 60 * 60  # ⏱️ registry cache: 6 hours
LIVE_TTL = 60 * 60  # ⏱️ live provider lists: 1 hour
LIVE_TIMEOUT = 2.5  # ⚡ per-provider HTTP budget (seconds)
OLLAMA_URL = "http://localhost:11434/api/tags"
OLLAMA_TIMEOUT = 0.6  # ⚡ local probe must never slow the UI

UNAVAILABLE_FILE = Path.home() / ".jimmy" / "unavailable_models.json"

# ⭐ curated popular models (litellm strings) — verified against the
#    available set before display, so this list can never show dead models
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

# 📡 providers exposing a models/list API we can verify against.
#    All are OpenAI-compatible {"data": [{"id": ...}]} responses except
#    Anthropic (x-api-key + version header, same response shape).
#    OpenRouter's list is public (no key needed).
_LIVE_ENDPOINTS: dict[str, dict[str, str]] = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/models",
        "env": "GROQ_API_KEY",
    },
    "openai": {
        "url": "https://api.openai.com/v1/models",
        "env": "OPENAI_API_KEY",
    },
    "deepseek": {
        "url": "https://api.deepseek.com/models",
        "env": "DEEPSEEK_API_KEY",
    },
    "mistral": {
        "url": "https://api.mistral.ai/v1/models",
        "env": "MISTRAL_API_KEY",
    },
    "xai": {
        "url": "https://api.x.ai/v1/models",
        "env": "XAI_API_KEY",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/models",
        "env": "",  # 🟢 public endpoint
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/models",
        "env": "ANTHROPIC_API_KEY",
        "headers": "anthropic-version:2023-06-01",
    },
}


@dataclass(frozen=True, slots=True)
class Catalog:
    """Snapshot of all discoverable providers → models.

    NOTE: the two helpers below live ON the dataclass — keep them here
    when editing fields (they were previously lost in an edit, which
    crashed the model picker with AttributeError).
    """

    providers: dict[str, list[str]]  # 📦 provider → litellm model strings
    popular: list[str]  # ⭐ verified popular models
    fetched_at: float  # ⏱️ epoch of the registry fetch
    verified: frozenset[str] = frozenset()  # ✅ providers live-checked

    def provider_env_var(self, provider: str) -> str:
        """🔑 API-key env var for a provider (convention + overrides)."""
        key = str(provider).strip().lower()
        if key in ENV_VAR_OVERRIDES:
            return ENV_VAR_OVERRIDES[key]
        return f"{key.upper().replace('-', '_')}_API_KEY"

    def provider_api_base(self, provider: str) -> str:
        """🌐 custom endpoint for a provider ('' = none)."""
        return API_BASE_OVERRIDES.get(str(provider).strip().lower(), "")


# ─────────────────────────────────────
# 🔍 fuzzy search
# ─────────────────────────────────────


def fuzzy_score(needle: str, haystack: str) -> int:
    """Subsequence match score.  0 = no match, higher = better.

    * exact substring → 100+ (earlier occurrence ranks higher)
    * otherwise every needle char must appear IN ORDER in the haystack
      (separators like - . _ / in the haystack are simply skipped, so
      "glm flash" matches "glm-4.6-flash" and "gpt4o" matches
      "openai/gpt-4o")
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


def smart_search(
    catalog: Catalog,
    query: str,
) -> tuple[list[str], list[str]]:
    """🔍 Fuzzy search across providers AND models.

    Returns ``(providers, models)`` — both ranked best-first:

        * providers ranked above models (a provider row groups its models)
        * models matched on the FULL litellm string and the bare model
          name, with spaces in the query ignored ("gpt 4o" works)
    """
    q = " ".join(query.lower().split())
    if not q:
        return list(catalog.providers), []

    compact = q.replace(" ", "")

    provider_hits: list[tuple[int, str]] = []
    model_hits: list[tuple[int, str]] = []

    for provider, models in catalog.providers.items():
        p_score = max(
            fuzzy_score(q, provider),
            fuzzy_score(compact, provider),
        )
        if p_score > 0:
            provider_hits.append((p_score + 5, provider))  # providers rank up

        for full in models:
            full_l = full.lower()
            short_l = full_l.split("/")[-1] if "/" in full_l else full_l
            s = max(
                fuzzy_score(q, full_l),
                fuzzy_score(q, short_l),
                fuzzy_score(compact, full_l),
                fuzzy_score(compact, short_l),
            )
            if s > 0:
                model_hits.append((s, full))

    provider_hits.sort(key=lambda t: t[0], reverse=True)
    model_hits.sort(key=lambda t: t[0], reverse=True)

    return (
        [p for _, p in provider_hits],
        [m for _, m in model_hits],
    )


def search(catalog: Catalog, query: str) -> tuple[list[str], list[str]]:
    """🔍 Search — now fuzzy (kept as an alias for compatibility)."""
    return smart_search(catalog, query)


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
# 📡 provider live models/list APIs
# ─────────────────────────────────────


def _as_full(provider: str, model_id: str) -> str:
    """Normalize a provider API id to a full litellm string.

    Avoids double prefixes when an API already returns ids that start
    with the provider name (some do for nested vendors).
    """
    model_id = model_id.strip()
    if model_id.startswith(f"{provider}/"):
        return model_id
    return f"{provider}/{model_id}"


def _fetch_live_models(provider: str) -> list[str] | None:
    """🌐 Query a provider's models/list API with the user's key.

    Returns bare model ids, or None when the provider can't be verified
    (no key configured, network error, bad response).  None means
    "fail open" — callers keep the registry as the source for it.
    """
    spec = _LIVE_ENDPOINTS.get(provider)
    if spec is None:
        return None

    headers = {"User-Agent": "jimmy-code"}

    extra = spec.get("headers", "")
    if extra and ":" in extra:
        name, _, value = extra.partition(":")
        headers[name.strip()] = value.strip()

    env_var = spec.get("env", "")
    if env_var:
        key = os.environ.get(env_var, "").strip()
        if not key:
            return None  # 🔑 no key → can't verify; registry stays source
        if provider == "anthropic":
            headers["x-api-key"] = key
        else:
            headers["Authorization"] = f"Bearer {key}"

    try:
        req = urllib.request.Request(spec["url"], headers=headers)
        with urllib.request.urlopen(req, timeout=LIVE_TIMEOUT) as r:
            data = json.loads(r.read().decode())
        ids = [str(item.get("id", "")).strip() for item in data.get("data", [])]
        ids = [i for i in ids if i]
        return ids or None
    except Exception:
        return None  # 🤷 unreachable → fail open, never crash the UI


# ─────────────────────────────────────
# 🏭 registry fetch
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


# ─────────────────────────────────────
# 💾 cache (performance only)
# ─────────────────────────────────────


def _load_cache() -> dict:
    try:
        data = json.loads(CACHE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(
    providers: dict[str, list[str]],
    fetched_at: float,
    live: dict[str, dict],
) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(
            json.dumps(
                {
                    "fetched_at": fetched_at,
                    "providers": providers,
                    "live": live,
                }
            )
        )
    except Exception:
        pass  # 💾 cache write failure is never fatal


# ─────────────────────────────────────
# ⚰️ unavailable models (404 loop)
# ─────────────────────────────────────


def _load_unavailable() -> dict[str, dict]:
    try:
        data = json.loads(UNAVAILABLE_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_unavailable(dead: dict[str, dict]) -> None:
    try:
        UNAVAILABLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        UNAVAILABLE_FILE.write_text(json.dumps(dead))
    except Exception:
        pass


def mark_unavailable(name: str, reason: str = "") -> None:
    """⚰️ Record that a model 404'd — get_catalog() will hide it."""
    dead = _load_unavailable()
    dead[name] = {"at": time.time(), "reason": reason[:200]}
    _save_unavailable(dead)


def is_marked_unavailable(name: str) -> bool:
    return name in _load_unavailable()


def is_model_not_found(exc: BaseException) -> bool:
    """True when an exception looks like a dead/deprecated model (404)."""
    if getattr(exc, "status_code", None) == 404:
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    markers = (
        "model_not_found",
        "model not found",
        "does not exist",
        "no longer available",
        "decommissioned",
    )
    return any(marker in text for marker in markers)


# ─────────────────────────────────────
# 🌐 catalog assembly
# ─────────────────────────────────────


def _verified_popular(providers: dict[str, list[str]]) -> list[str]:
    """⭐ keep only popular entries that actually exist right now."""
    everything = {m for models in providers.values() for m in models}
    return [p for p in POPULAR if p in everything]


def get_catalog(*, force: bool = False, live: bool = False) -> Catalog:
    """🌐 Build the catalog.

    force=True → re-pull the LiteLLM registry (cache bypassed).
    live=True  → ALSO query provider models/list APIs with the user's
                 keys, in parallel with bounded timeouts (the 🔄 button;
                 the TUI runs this via asyncio.to_thread, never on the
                 render loop).

    Marked-unavailable models are ALWAYS excluded — the cache is never
    authoritative over reality.  Provider live lists are intersected
    with the registry: retired entries are dropped, live-only entries
    (new releases) are added, unreachable providers fail open.
    """
    now = time.time()
    cached = {} if force else _load_cache()
    cache_fresh = bool(cached) and now - cached.get("fetched_at", 0) < CACHE_TTL
    live_cache = cached.get("live", {}) if isinstance(cached.get("live"), dict) else {}

    # 1️⃣ registry (cache → fresh serve; stale/forced → refetch)
    providers: dict[str, list[str]] = {}
    if cache_fresh:
        providers = {
            p: list(ms) for p, ms in cached.get("providers", {}).items() if isinstance(ms, list)
        }
    if not providers:
        providers = _from_litellm()
    if not providers:
        # 🛟 registry unavailable → last-resort cache, whatever its age
        providers = {
            p: list(ms) for p, ms in cached.get("providers", {}).items() if isinstance(ms, list)
        }

    # 2️⃣ live verification — authoritative where we can get it
    applied: dict[str, list[str]] = {}

    if live:
        todo = [p for p in providers if p in _LIVE_ENDPOINTS]
        if todo:
            with ThreadPoolExecutor(max_workers=min(6, len(todo))) as pool:
                futures = {p: pool.submit(_fetch_live_models, p) for p in todo}
                for p, fut in futures.items():
                    ids = fut.result()
                    if ids is not None:
                        applied[p] = ids
    else:
        # serve FRESH cached live lists; stale ones are ignored (fail open)
        for p in providers:
            if p not in _LIVE_ENDPOINTS:
                continue
            entry = live_cache.get(p) or {}
            if now - entry.get("fetched_at", 0) < LIVE_TTL:
                ids = entry.get("models")
                if isinstance(ids, list):
                    applied[p] = [str(i) for i in ids if str(i).strip()]

    for provider, ids in applied.items():
        allowed = {_as_full(provider, i) for i in ids}
        kept = [m for m in providers.get(provider, []) if m in allowed]
        for extra in sorted(allowed - set(kept)):
            kept.append(extra)  # 🆕 live-only models (brand-new releases)
        if kept:
            providers[provider] = sorted(set(kept))
        elif provider in providers:
            del providers[provider]  # 🪦 provider serves nothing anymore

    # 3️⃣ 🦙 Ollama — probed fresh every call (local models come and go)
    ollama = _fetch_ollama()
    if ollama:
        existing = set(providers.get("ollama", []))
        providers["ollama"] = sorted(existing | set(ollama))

    # 4️⃣ ⚰️ runtime-unavailable models never come back in any list
    dead = _load_unavailable()
    if dead:
        providers = {p: [m for m in ms if m not in dead] for p, ms in providers.items()}
        providers = {p: ms for p, ms in providers.items() if ms}

    # 5️⃣ 💾 persist (performance only — never authoritative)
    if providers:
        merged_live = dict(live_cache)
        for p, ids in applied.items():
            merged_live[p] = {"fetched_at": now, "models": ids}
        saved_at = cached.get("fetched_at", now) if (cache_fresh and not force) else now
        _save_cache(providers, saved_at, merged_live)

    return Catalog(
        providers=providers,
        popular=_verified_popular(providers),
        fetched_at=now,
        verified=frozenset(applied),
    )


# ─────────────────────────────────────
# 💾 API key persistence (~/.jimmy/.env)
# ─────────────────────────────────────

ENV_FILE = Path.home() / ".jimmy" / ".env"


def save_key_to_env(env_var: str, key: str) -> None:
    """💾 Persist a pasted API key to ~/.jimmy/.env (never in models.json)."""
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


def load_env_file(path: Path | None = None) -> int:
    """🔑 Load KEY=VALUE pairs from ~/.jimmy/.env into os.environ.

    Real environment variables always WIN (never overridden).
    Returns how many variables were injected.

    WHY: save_key_to_env() writes keys here + sets os.environ live —
    but a FRESH process (❯ jimmy) never reads the file automatically.
    factory.create_provider() calls this before raising MissingAPIKeyError,
    so TUI-added keys survive restarts.
    """
    env_path = path or ENV_FILE
    if not env_path.exists():
        return 0

    loaded = 0
    try:
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if key not in os.environ:  # 🛡️ real env wins
                os.environ[key] = value
                loaded += 1
    except Exception:
        pass  # 🔑 env loading must never crash the boot

    return loaded
