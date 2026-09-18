"""Shared helpers & constants — pure functions, no Textual widgets.

Every ``self.app.action_*`` call from a widget goes through :func:`jimmy`,
which returns the running app cast to JimmyApp.  That single helper is
what silences the Pylance ``Cannot access attribute ... for class
"App[Unknown]"`` spam across the whole TUI.
"""

from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from rich.markup import escape
from textual.widget import Widget

if TYPE_CHECKING:
    from ..app import JimmyApp

# ── constants ──────────────────────────────────────────────────────────

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"  # live rows (thinking / tools / navbar)
WAVE_GLYPHS = "▁▂▃▄▅▆▇█"  # equalizer waves (home + bottom strip)
MAX_PASTE_CHARS = 100_000  # absurd pastes are capped, never freeze
IS_MAC = sys.platform == "darwin"  # hints render ⌘ instead of "ctrl"


def jimmy(widget: Widget) -> "JimmyApp":
    """The running app, correctly typed as JimmyApp (Pylance-friendly)."""
    return cast("JimmyApp", widget.app)


# ── formatting ─────────────────────────────────────────────────────────


def format_duration(seconds: float) -> str:
    """Human duration: 84ms · 4.8s · 1m 02s."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    remaining = int(seconds % 60)
    return f"{minutes}m {remaining:02d}s"


def compact_count(value: int) -> str:
    """17300 -> '17.3k' · 263 -> '263' · 2000000 -> '2M'."""

    def trim(x: float, suffix: str) -> str:
        return f"{x:.1f}".rstrip("0").rstrip(".") + suffix

    if value >= 1_000_000:
        return trim(value / 1_000_000, "M")
    if value >= 1_000:
        return trim(value / 1_000, "k")
    return str(value)


def clip(text: str, limit: int = 48) -> str:
    """Truncate long paths / commands / errors for tidy rows."""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def short_model(model: str) -> str:
    """'gemini/gemini-3.5-flash-lite' -> 'gemini-3.5-flash-lite'."""
    text = str(model).strip()
    return text.split("/")[-1] or text


def pretty_pwd() -> str:
    """The working directory with $HOME abbreviated to '~'."""
    cwd = str(Path.cwd())
    home = str(Path.home())
    return cwd.replace(home, "~", 1) if cwd.startswith(home) else cwd


def blend_hex(start: str, end: str, t: float) -> str:
    """Linear-interpolate two '#rrggbb' colors (gradients / shimmer)."""
    t = max(0.0, min(1.0, t))
    a = (int(start[1:3], 16), int(start[3:5], 16), int(start[5:7], 16))
    b = (int(end[1:3], 16), int(end[3:5], 16), int(end[5:7], 16))
    return "#{:02x}{:02x}{:02x}".format(*(round(x + (y - x) * t) for x, y in zip(a, b)))


def keycap(key: str, label: str) -> str:
    """Render a compact keyboard key + label in Rich markup."""
    shown = key

    # macOS: Ctrl+X -> ⌘X
    if IS_MAC and shown.lower().startswith("ctrl+"):
        shown = "⌘" + shown[5:]

    return f"[#A8B8FF on #1A2242] {escape(shown)} [/][#667089] {escape(label)}[/]"


# ── domain mapping ─────────────────────────────────────────────────────


def _shell_icon(command: str) -> tuple[str, str]:
    """🗺️ command-aware icon for shell rows — git looks like git."""
    low = " ".join(command.lower().split())
    parts = low.split()
    first = parts[0] if parts else ""

    if first == "git":
        sub = parts[1] if len(parts) > 1 else ""
        if sub.startswith("commit"):
            return "📦", "Committing"
        if sub in ("push", "pull", "fetch"):
            return "📡", "Syncing"
        if sub in ("add", "restore", "checkout", "rm", "mv", "stash"):
            return "🗃️", "Staging"
        if sub in ("diff", "show"):
            return "🧾", "Checking diff"
        if sub in ("status", "log", "branch", "tag", "remote"):
            return "🌿", "Checking git"
        return "🌿", "Git"
    if low.startswith("pytest") or "pytest" in parts[:3]:
        return "🧪", "Testing"
    if first in ("python", "python3", "node", "deno", "tsx"):
        return "🐍", "Executing"
    if low.startswith("npm run") or first in ("npx", "bunx"):
        return "⚙️", "Executing"
    if first in ("pip", "pip3", "uv", "uvx", "poetry") or low.startswith("cargo build"):
        return "📦", "Installing"
    if first in ("npm", "pnpm", "yarn", "bun") and ("install" in parts or "add" in parts):
        return "📦", "Installing"
    if first in ("curl", "wget", "http", "https"):
        return "🌐", "Fetching"
    if first in ("ls", "dir", "cat", "head", "tail", "find", "tree", "pwd", "du"):
        return "📂", "Inspecting"
    if first in ("mkdir", "cp", "mv", "rm", "touch", "rmdir"):
        return "🗂️", "File ops"
    if first in ("docker", "podman", "docker-compose"):
        return "🐳", "Docker"
    if first in ("grep", "rg", "awk", "sed"):
        return "🔍", "Filtering"
    return "▶️", "Running"


def tool_display(tool_name: str, arguments: dict[str, Any]) -> tuple[str, str, str]:
    """Map a tool call to (icon, action, detail) for readable rows.

    Shell rows are COMMAND-AWARE: `git status` -> 🌿, `pytest` -> 🧪,
    `pip install` -> 📦, so a wall of shell calls still reads at a glance.

    e.g.  search_files {"query": "jwt"}  -> ("🔍", "Searching", '"jwt"')
          read_files   {"paths": [..]}   -> ("📖", "Reading", "a.md, b.py")
          shell {"command": "git status"} -> ("🌿", "Checking git", "git status")
    """
    mapping = {
        "read_file": ("📖", "Reading"),
        "read_files": ("📖", "Reading"),
        "write_file": ("📝", "Writing"),
        "write_files": ("📝", "Writing"),
        "edit_file": ("✏️", "Editing"),
        "edit_files": ("✏️", "Editing"),
        "search_files": ("🔍", "Searching"),
        "search_file": ("🔍", "Searching"),
        "grep": ("🔍", "Searching"),
        "list_files": ("📂", "Listing"),
        "glob": ("📂", "Listing"),
    }

    # 💻 shell → command-aware icon (git/pytest/pip/... each get their own)
    if tool_name in ("shell", "run_shell"):
        command = ""
        for key in ("command", "cmd"):
            value = arguments.get(key)
            if value:
                command = str(value)
                break
        icon, action = _shell_icon(command)
        return icon, action, clip(command)

    icon, action = mapping.get(tool_name, ("🛠️", "Using"))

    # Many agents pass lists (paths=[..]); join them so the row says WHAT
    # is being read/edited, not just "Reading".
    detail = ""
    quoted = False
    for key in (
        "path",
        "file_path",
        "filepath",
        "filename",
        "paths",
        "files",
        "file_paths",
        "directory",
        "dir",
        "folder",
        "query",
        "pattern",
        "glob",
        "url",
        "message",
    ):
        value = arguments.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            detail = ", ".join(str(v) for v in value if str(v).strip())
        else:
            detail = str(value).strip()
        quoted = key in ("query", "pattern")
        if detail:
            break

    if detail and quoted:
        detail = f'"{detail}"'
    return icon, action, clip(detail)


# ── error classification (the friendly error card) ─────────────────────


def classify_error(error: BaseException) -> tuple[str, str, str]:
    """Map an exception to (icon, short title, human message).

    401/403   🔐 API key · 429 ⏳ Rate limit · 500 ⚠️ Provider ·
    502/503   🔌 Unavailable · timeout ⏱️ · network 🌐 · unknown ❌
    """
    raw = str(error)
    low = f"{type(error).__name__}: {raw}".lower()

    code: int | None = getattr(error, "status_code", None)
    if code is None:
        match = re.search(r"\b([45]\d{2})\b", raw)
        code = int(match.group(1)) if match else None

    if code in (401, 403):
        return (
            "🔐",
            "API key problem",
            f"Jimmy's credentials were rejected (HTTP {code}). "
            "Check the API key and its permissions.",
        )
    if code == 429:
        return (
            "⏳",
            "Rate limited",
            "The provider is throttling requests (HTTP 429). Wait a little while, then retry.",
        )
    if code == 500:
        return ("⚠️", "Provider error", "The model provider hit an internal error (HTTP 500).")
    if code in (502, 503):
        return (
            "🔌",
            "Provider temporarily unavailable",
            f"The provider is temporarily unavailable (HTTP {code}) "
            "— this usually resolves on its own. Try again shortly.",
        )
    if "timeout" in low or "timed out" in low:
        return (
            "⏱️",
            "Request timed out",
            "The provider took too long to respond. Retry — it often works on the second try.",
        )
    if any(
        k in low for k in ("connection", "network", "unreachable", "getaddrinfo", "dns", "resolve")
    ):
        return ("🌐", "Network problem", "Couldn't reach the provider — check your connection.")
    return ("❌", "Something went wrong", clip(raw, 140) or type(error).__name__)


def error_detail(error: BaseException) -> str:
    """Full traceback text for the expandable error view (capped)."""
    try:
        text = "".join(traceback.format_exception(type(error), error, error.__traceback__)).strip()
    except Exception:
        text = ""
    if not text:
        text = f"{type(error).__name__}: {error}"
    lines = text.splitlines()
    if len(lines) > 60:
        lines = lines[-60:]
        lines.insert(0, f"… ({len(lines)} more lines above)")
    return "\n".join(lines)
