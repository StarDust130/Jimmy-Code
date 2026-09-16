"""Shared fixtures for TUI tests.   Run:  pytest tests/tui -q

Design notes
    * No pytest-asyncio needed: async scenarios run via asyncio.run().
    * The real Agent is replaced (tui.app.Agent) so no LLM/network runs.
    * Sound is stubbed so tests never spawn audio subprocesses.
    * ``cast`` is used where test fakes replace real types — that is what
      keeps Pylance quiet without weakening the production code.
"""

from __future__ import annotations

import asyncio
import functools
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Callable, cast

import pytest

from tui.app import JimmyApp
from tui.screens.home import HomeScreen

if TYPE_CHECKING:
    from jimmy.llm.provider import LLMProvider
    from tui.kit.sound import SoundPlayer


class FakeProvider:
    """Only ``.model`` is read by the TUI (typed as LLMProvider at use)."""

    def __init__(self, model: str = "test/test-flash") -> None:
        self.model = model


class FakeAgent:
    """Agent stand-in.  Assign ``stream_impl`` per test with a factory."""

    def __init__(self, provider: Any) -> None:
        self.provider = provider
        self.stream_impl: Callable[[str], Any] | None = None

    async def stream(self, text: str):
        if self.stream_impl is None:
            return
        async for event in self.stream_impl(text):
            yield event


class FakeSound:
    """Sound stand-in — records calls, never touches the OS."""

    def __init__(self) -> None:
        self.play_calls = 0
        self.stop_calls = 0
        self.playing = False

    @property
    def is_playing(self) -> bool:
        return self.playing

    def play_startup(self) -> None:
        self.play_calls += 1
        self.playing = True

    def play(self, path: Any) -> None:
        self.play_calls += 1
        self.playing = True

    def stop(self) -> None:
        self.stop_calls += 1
        self.playing = False


class FakeEvent:
    """Duck-typed AgentEvent — the TUI reads only .type and .data."""

    def __init__(self, type: str, **data: Any) -> None:
        self.type = type
        self.data = data


def usage(inp: int = 0, out: int = 0) -> SimpleNamespace:
    """Usage object shaped like the agent's (ints are read via int())."""
    return SimpleNamespace(input_tokens=inp, output_tokens=out, total_tokens=inp + out)


# ── click stand-ins for palette on_click tests ─────────────────────────


class _FakeControl:
    """Mimics the DOM node a real Click would carry (id + parent chain)."""

    def __init__(self, node_id: str | None = None, parent: Any = None) -> None:
        self.id = node_id
        self.parent = parent


class FakeClick:
    """Stand-in for events.Click.

    The palette's ``on_click`` only uses ``event.control`` (.id/.parent
    for the ancestor walk) and ``event.stop()``.  Building a real Click
    event requires terminal geometry and varies across Textual versions,
    so tests drive the handler with this stub and ``cast`` it.
    """

    def __init__(self, control: Any) -> None:
        self.control = control
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def scrim_click() -> FakeClick:
    """A click that landed OUTSIDE the #palette card (on the dim scrim):
    its control has no id and no parent → the ancestor walk never finds
    #palette → the palette must close."""
    return FakeClick(_FakeControl(node_id=None, parent=None))


# ── async helpers ──────────────────────────────────────────────────────


def tui_test(fn: Callable) -> Callable:
    """Run an async test with asyncio.run — no pytest-asyncio plugin."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


async def settle(app: JimmyApp, pilot: Any, timeout_s: float = 2.0) -> None:
    """Pump the loop until the running turn finishes (or timeout)."""
    deadline = time.monotonic() + timeout_s
    while app._busy and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
        await pilot.pause()
    await pilot.pause()


async def leave_home(app: JimmyApp, pilot: Any) -> None:
    """Drop straight into the workspace (skip the intro animation)."""
    if isinstance(app.screen, HomeScreen):
        app.pop_screen()
        await pilot.pause()
    app.composer.focus_input()
    await pilot.pause()


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def fake_agent(monkeypatch: pytest.MonkeyPatch) -> FakeAgent:
    """Swap tui.app.Agent BEFORE JimmyApp constructs it."""
    agent = FakeAgent(None)
    monkeypatch.setattr("tui.app.Agent", lambda provider: agent)
    return agent


@pytest.fixture
def app(fake_agent: FakeAgent) -> JimmyApp:
    application = JimmyApp(provider=cast("LLMProvider", FakeProvider()))
    application.sound = cast("SoundPlayer", FakeSound())
    return application


@pytest.fixture(autouse=True)
def restore_theme():
    """Theme tests mutate global state — always restore violet."""
    yield
    from tui.kit.theme import THEME, THEMES, rebuild_flow

    THEME["name"] = "violet"
    THEME["accent"] = THEMES["violet"]["accent"]
    THEME["accent2"] = THEMES["violet"]["accent2"]
    rebuild_flow(THEMES["violet"]["stops"])
