from pathlib import Path

import pytest

from jimmy.agent.main_loop.agent_loop import AgentLoop
from jimmy.agent.main_loop.agent_turn import AgentTurn
from jimmy.cli.tui.app import JimmyTUI
from jimmy.context.context import ContextManager
from jimmy.llm.base import LLMProvider, LLMResponse
from jimmy.llm.errors import LLMProviderError
from jimmy.llm.gemini import GeminiProvider
from jimmy.observability.metrics import Observability, RunMetrics
from jimmy.session.json_store import JsonSessionStore
from jimmy.state.session import SessionState
from jimmy.tools.defaults import create_default_registry


class CapturingLLM(LLMProvider):
    def __init__(self) -> None:
        self.tools: list[dict] = []
        self.messages: list[dict] = []

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        self.messages = messages
        self.tools = tools or []
        return LLMResponse(
            content="Done.",
            tool_calls=[],
            assistant_message={"role": "assistant", "content": "Done."},
        )


class RateLimitedLLM(LLMProvider):
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        self.calls += 1
        raise LLMProviderError("quota", code="rate_limit", retryable=True)


def test_non_commit_task_does_not_offer_commit_tool(tmp_path: Path) -> None:
    llm = CapturingLLM()
    agent = AgentLoop(
        llm=llm,
        tools=create_default_registry(tmp_path),
        workspace=tmp_path,
        session_store=JsonSessionStore(tmp_path),
    )

    agent.run("Create a folder called gitGraph with a browser app.")

    names = [schema["function"]["name"] for schema in llm.tools]
    assert "git_commit" not in names
    context = next(message["content"] for message in llm.messages if message.get("role") == "system" and "active_task_context" in message.get("content", ""))
    assert "gitGraph" in context


def test_static_frontend_task_uses_frontend_verifier_not_shell(tmp_path: Path) -> None:
    llm = CapturingLLM()
    agent = AgentLoop(
        llm=llm,
        tools=create_default_registry(tmp_path),
        workspace=tmp_path,
        session_store=JsonSessionStore(tmp_path),
    )

    agent.run("Fix the HTML, CSS, and JavaScript browser app in gitGraph.")

    names = [schema["function"]["name"] for schema in llm.tools]
    assert "verify_frontend" in names
    assert "run_shell" not in names


def test_rate_limit_waits_once_then_stops_if_the_quota_is_still_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    llm = RateLimitedLLM()
    turn = AgentTurn(llm, ContextManager(), Observability())
    state = SessionState(task="test", messages=[{"role": "user", "content": "test"}])
    delays: list[float] = []
    monkeypatch.setattr("jimmy.agent.main_loop.agent_turn.time.sleep", delays.append)

    with pytest.raises(LLMProviderError, match="quota"):
        turn.run(state, "session", RunMetrics(), [])

    assert llm.calls == 2
    assert delays == [60.0]


def test_rate_limit_error_is_compact_for_the_chat() -> None:
    message = JimmyTUI._error_summary(
        RuntimeError("429 RESOURCE_EXHAUSTED: Gemini rate limit reached. " + "details " * 200)
    )

    assert message == "Gemini quota reached. Wait for the quota window, then resume this session."


def test_gemini_retry_delay_is_parsed_from_quota_error() -> None:
    assert GeminiProvider._retry_after_seconds("retryDelay': '41s'") == 41.0
