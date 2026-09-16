"""Pure-function tests for kit.helpers — no app boot required."""

from __future__ import annotations

import sys

from tui.kit.helpers import (
    IS_MAC,
    MAX_PASTE_CHARS,
    classify_error,
    clip,
    compact_count,
    error_detail,
    format_duration,
    keycap,
    pretty_pwd,
    short_model,
    tool_display,
)


def _http_error(message: str, status_code: int | None = None) -> Exception:
    exc = RuntimeError(message)
    if status_code is not None:
        exc.status_code = status_code  # type: ignore[attr-defined]
    return exc


# ── formatting ─────────────────────────────────────────────────────────


def test_format_duration_ms() -> None:
    assert format_duration(0.084) == "84ms"


def test_format_duration_seconds() -> None:
    assert format_duration(4.8) == "4.8s"


def test_format_duration_minutes() -> None:
    assert format_duration(62) == "1m 02s"


def test_compact_count_plain() -> None:
    assert compact_count(667) == "667"
    assert compact_count(263) == "263"


def test_compact_count_k() -> None:
    assert compact_count(17_300) == "17.3k"
    assert compact_count(1_000) == "1k"


def test_compact_count_m() -> None:
    assert compact_count(2_000_000) == "2M"


def test_short_model_strips_provider_prefix() -> None:
    assert short_model("gemini/gemini-3.5-flash-lite") == "gemini-3.5-flash-lite"
    assert short_model("openai/gpt-4o") == "gpt-4o"


def test_short_model_without_prefix() -> None:
    assert short_model("claude-local") == "claude-local"


def test_clip_truncates_with_ellipsis() -> None:
    assert clip("abcdefghij", limit=5) == "abcd…"
    assert clip("  hi  ") == "hi"


# ── tool labels ────────────────────────────────────────────────────────


def test_tool_display_known_tool_with_path() -> None:
    icon, action, detail = tool_display("read_file", {"path": "README.md"})
    assert (icon, action) == ("📖", "Reading")
    assert detail == "README.md"


def test_tool_display_joins_path_lists() -> None:
    _, action, detail = tool_display("read_files", {"paths": ["a.md", "b.py"]})
    assert action == "Reading"
    assert detail == "a.md, b.py"


def test_tool_display_quotes_search_terms() -> None:
    _, action, detail = tool_display("search_files", {"query": "jwt"})
    assert action == "Searching"
    assert detail == '"jwt"'


def test_tool_display_unknown_tool() -> None:
    icon, action, detail = tool_display("warp_drive", {})
    assert action == "Using"
    assert detail == ""


# ── error classification ───────────────────────────────────────────────


def test_classify_auth_401() -> None:
    icon, title, _ = classify_error(_http_error("denied", 401))
    assert icon == "🔐"
    assert "API key" in title


def test_classify_auth_403() -> None:
    icon, _, _ = classify_error(_http_error("forbidden", 403))
    assert icon == "🔐"


def test_classify_rate_limit_429_says_wait() -> None:
    icon, _, message = classify_error(_http_error("slow down", 429))
    assert icon == "⏳"
    assert "wait" in message.lower()


def test_classify_500() -> None:
    icon, _, _ = classify_error(_http_error("internal", 500))
    assert icon == "⚠️"


def test_classify_502_503_from_message_text() -> None:
    for code in (502, 503):
        icon, _, _ = classify_error(_http_error(f"http {code} unavailable"))
        assert icon == "🔌"


def test_classify_timeout() -> None:
    icon, _, _ = classify_error(RuntimeError("request timed out after 30s"))
    assert icon == "⏱️"


def test_classify_network() -> None:
    icon, _, _ = classify_error(RuntimeError("connection refused"))
    assert icon == "🌐"


def test_classify_unknown() -> None:
    icon, title, _ = classify_error(ValueError("weird"))
    assert icon == "❌"
    assert title == "Something went wrong"


def test_error_detail_contains_type_and_message() -> None:
    try:
        raise ValueError("kaboom")
    except ValueError as exc:
        detail = error_detail(exc)
    assert "ValueError" in detail
    assert "kaboom" in detail


# ── misc ───────────────────────────────────────────────────────────────


def test_keycap_format() -> None:
    cap = keycap("ctrl+h", "home")
    assert "ctrl+h" in cap
    if not IS_MAC:
        assert "⌘" not in cap


def test_pretty_pwd_is_nonempty_string() -> None:
    value = pretty_pwd()
    assert isinstance(value, str) and value


def test_paste_limit_is_sane() -> None:
    assert MAX_PASTE_CHARS >= 10_000


def test_platform_flag_matches_sys() -> None:
    assert IS_MAC == (sys.platform == "darwin")
