"""🏷️ titles — sanitize · heuristic · AI streaming."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jimmy.sessions.title import generate_title, heuristic_title, sanitize_title


def test_sanitize_strips_quotes_newlines_and_clips() -> None:
    assert sanitize_title('  "Fix the   login bug"\n') == "Fix the login bug"
    assert sanitize_title("`refactor auth module`") == "refactor auth module"
    long = sanitize_title("x" * 100)
    assert len(long) == 48 and long.endswith("…")


def test_sanitize_empty() -> None:
    assert sanitize_title("   ") == ""
    assert sanitize_title("") == ""


def test_heuristic_uses_first_user_text() -> None:
    assert heuristic_title(["commit the tests", "more"]) == "commit the tests"
    assert heuristic_title([]) == "New session"
    assert heuristic_title(["", "   "]) == "New session"


class _FakeProvider:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    async def stream(self, messages, tools=None):
        for chunk in self._chunks:
            yield SimpleNamespace(kind="text", text=chunk)
        yield SimpleNamespace(kind="done", result=None)


class _BoomProvider:
    async def stream(self, messages, tools=None):
        raise RuntimeError("provider down")
        yield  # pragma: no cover — makes it an async generator


@pytest.mark.asyncio
async def test_generate_title_streams_and_sanitizes() -> None:
    provider = _FakeProvider(['"Fix the ', "login ", 'bug"'])
    title = await generate_title(provider, ["fix login", "now tests"])
    assert title == "Fix the login bug"


@pytest.mark.asyncio
async def test_generate_title_none_on_empty() -> None:
    assert await generate_title(_FakeProvider([]), ["hello"]) is None
    assert await generate_title(_FakeProvider(["   "]), ["hello"]) is None


@pytest.mark.asyncio
async def test_generate_title_raises_on_provider_failure() -> None:
    with pytest.raises(RuntimeError):
        await generate_title(_BoomProvider(), ["hello"])
