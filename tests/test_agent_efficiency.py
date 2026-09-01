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


def test_ordinary_edit_does_not_offer_shell(tmp_path: Path) -> None:
    llm = CapturingLLM()
    agent = AgentLoop(
        llm=llm,
        tools=create_default_registry(tmp_path),
        workspace=tmp_path,
        session_store=JsonSessionStore(tmp_path),
    )

    agent.run("Add a comment above greeting in main.py. Do not commit anything.")

    names = [schema["function"]["name"] for schema in llm.tools]
    assert "run_shell" not in names
    assert "git_commit" not in names


def test_explicit_test_request_keeps_shell_available(tmp_path: Path) -> None:
    llm = CapturingLLM()
    agent = AgentLoop(
        llm=llm,
        tools=create_default_registry(tmp_path),
        workspace=tmp_path,
        session_store=JsonSessionStore(tmp_path),
    )

    agent.run("Run the test suite.")

    names = [schema["function"]["name"] for schema in llm.tools]
    assert "run_shell" in names


def test_create_task_prefers_create_files_and_edit_task_prefers_edit_file(tmp_path: Path) -> None:
    for task, expected, absent in (
        ("Create hello.txt.", "create_files", "edit_file"),
        ("Improve the existing README.md.", "edit_file", "create_files"),
    ):
        llm = CapturingLLM()
        agent = AgentLoop(
            llm=llm,
            tools=create_default_registry(tmp_path),
            workspace=tmp_path,
            session_store=JsonSessionStore(tmp_path),
        )
        agent.run(task)
        names = [schema["function"]["name"] for schema in llm.tools]
        assert expected in names
        assert absent not in names


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


def test_daily_quota_error_explains_project_key_scope() -> None:
    message = JimmyTUI._error_summary(
        RuntimeError(
            "429 RESOURCE_EXHAUSTED: "
            "GenerateRequestsPerDayPerProjectModel-FreeTier quota exceeded"
        )
    )

    assert message == (
        "Gemini daily quota is exhausted for this project. "
        "Use a key from another Google project or wait for reset."
    )


def test_gemini_retry_delay_is_parsed_from_quota_error() -> None:
    assert GeminiProvider._retry_after_seconds("retryDelay': '41s'") == 41.0


def test_blocked_repeated_tool_attempts_are_not_counted_as_repeated_calls() -> None:
    from evals.trace import TraceCollector

    trace = TraceCollector("E04", "Create hello.txt.", Path("/tmp/trace"))
    trace.on_event(type("Event", (), {"kind": "tool_start", "tool_name": "read_file", "arguments": {"path": "hello.txt"}})())
    trace.on_event(type("Event", (), {"kind": "tool_end", "message": "ok", "elapsed": 0.1})())
    trace.on_event(type("Event", (), {"kind": "tool_start", "tool_name": "read_file", "arguments": {"path": "hello.txt"}})())
    trace.on_event(type("Event", (), {"kind": "tool_end", "message": "blocked", "elapsed": 0.0})())

    assert trace.trace.repeated_tools == 0
    assert trace.trace.tool_calls == 2


def test_gemini_429_error_is_normalized_without_name_error() -> None:
    class FakeGeminiError(Exception):
        def __init__(self, message: str, code: int) -> None:
            super().__init__(message)
            self.code = code

    error = FakeGeminiError("429 RESOURCE_EXHAUSTED: retryDelay': '41s'", 429)
    normalized = GeminiProvider._normalize_error(error)

    assert normalized.code == "rate_limit"
    assert normalized.retryable is True
    assert normalized.retry_after == 41.0


def test_gemini_daily_quota_error_is_not_retried() -> None:
    class FakeGeminiError(Exception):
        def __init__(self, message: str, code: int) -> None:
            super().__init__(message)
            self.code = code

    error = FakeGeminiError(
        "429 RESOURCE_EXHAUSTED: GenerateRequestsPerDay quota exceeded",
        429,
    )
    normalized = GeminiProvider._normalize_error(error)

    assert normalized.code == "quota_exhausted"
    assert normalized.retryable is False
    assert normalized.retry_after is None
