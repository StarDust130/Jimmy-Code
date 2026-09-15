"""Theme engine — 4 real palettes, applied LIVE.

``THEME`` is module-level mutable state read by every painter; switching
a theme rebuilds the 256-stop ``CYBER`` flow palette IN PLACE (so every
existing reference stays valid) and repaints anything that reads THEME.
"""

from __future__ import annotations

from typing import Any

from .helpers import blend_hex

THEMES: dict[str, dict[str, Any]] = {
    "violet": {
        "stops": ("#a855f7", "#7c3aed", "#4f46e5", "#22d3ee", "#f472b6", "#a855f7"),
        "accent": "#c084fc",
        "accent2": "#22d3ee",
    },
    "ember": {
        "stops": ("#f59e0b", "#fb923c", "#f87171", "#f472b6", "#fbbf24", "#f59e0b"),
        "accent": "#fbbf24",
        "accent2": "#fb923c",
    },
    "frost": {
        "stops": ("#22d3ee", "#38bdf8", "#818cf8", "#a5f3fc", "#67e8f9", "#22d3ee"),
        "accent": "#22d3ee",
        "accent2": "#93c5fd",
    },
    "matrix": {
        "stops": ("#22c55e", "#4ade80", "#a3e635", "#10b981", "#86efac", "#22c55e"),
        "accent": "#34d399",
        "accent2": "#a3e635",
    },
}
THEME_ORDER: tuple[str, ...] = ("violet", "ember", "frost", "matrix")

THEME: dict[str, Any] = {
    "name": "violet",
    "accent": THEMES["violet"]["accent"],
    "accent2": THEMES["violet"]["accent2"],
}

CYBER: list[str] = []


def rebuild_flow(stops: tuple[str, ...]) -> None:
    """Rebuild the 256-stop flow palette IN PLACE (references stay valid)."""
    palette: list[str] = []
    for i in range(256):
        pos = i / 255 * (len(stops) - 1)
        k = min(int(pos), len(stops) - 2)
        palette.append(blend_hex(stops[k], stops[k + 1], pos - k))
    CYBER[:] = palette


rebuild_flow(THEMES["violet"]["stops"])


def flow(hue: float) -> str:
    """Map a hue in [0, 1) to the precomputed theme flow palette."""
    return CYBER[int((hue % 1.0) * 255) & 255]


_VERSION_CACHE: str | None = None


def app_version() -> str:
    """Best-effort package version for the home status line."""
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        for package in ("jimmy", "jimmy-code"):
            try:
                from importlib.metadata import version

                _VERSION_CACHE = version(package)
                break
            except Exception:
                continue
        _VERSION_CACHE = _VERSION_CACHE or "0.1.0"
    return _VERSION_CACHE
