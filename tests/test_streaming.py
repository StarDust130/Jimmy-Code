from __future__ import annotations

from typing import Any

from jimmy.agent.main_loop.agent_turn import AgentTurn
from jimmy.llm.base import LLMProvider, LLMResponse
from jimmy.llm.streaming import LLMStreamChunk


class FakeMetrics:
    def __init__(self) -> None:
        self.failures = 0
        self.turns = 0
        self.llm_usage: list[Any] = []

    def add_llm_usage(self, **kwargs: Any) -> None:
        self.llm_usage.append(kwargs)


class FakeObservability:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.append((kind, payload))


class FakeContextManager:
    def prepare(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return messages


class StreamingLLM(LLMProvider):
    model = "fake-stream"

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise AssertionError("chat() should not be used")

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ):
        yield LLMStreamChunk(text="Hello ")
        yield LLMStreamChunk(text="Thor")
        yield LLMStreamChunk(
            response=LLMResponse(
                content="Hello Thor",
                tool_calls=[],
                assistant_message={
                    "role": "assistant",
                    "content": "Hello Thor",
                },
            )
        )


class ChatOnlyLLM(LLMProvider):
    model = "fake-chat"

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        return LLMResponse(
            content="Fallback answer",
            tool_calls=[],
            assistant_message={
                "role": "assistant",
                "content": "Fallback answer",
            },
        )


def make_turn(llm: LLMProvider) -> tuple[AgentTurn, FakeObservability]:
    observability = FakeObservability()
    turn = AgentTurn(
        llm=llm,
        context_manager=FakeContextManager(),  # type: ignore[arg-type]
        observability=observability,  # type: ignore[arg-type]
    )
    return turn, observability


def make_state() -> Any:
    from jimmy.state.session import SessionState

    state = SessionState(
        task="say hello",
        messages=[
            {
                "role": "user",
                "content": "say hello",
            }
        ],
    )
    state.next_turn()
    return state


def test_native_stream_emits_chunks_in_order() -> None:
    turn, observability = make_turn(StreamingLLM())
    deltas: list[str] = []
    metrics = FakeMetrics()

    response = turn.run(
        state=make_state(),
        session_id="test-session",
        metrics=metrics,  # type: ignore[arg-type]
        tools=[],
        task_turn=1,
        on_text_delta=deltas.append,
    )

    assert deltas == ["Hello ", "Thor"]
    assert response.content == "Hello Thor"
    assert any(kind == "llm_call" for kind, _ in observability.events)


def test_chat_only_provider_still_works() -> None:
    turn, _ = make_turn(ChatOnlyLLM())
    deltas: list[str] = []
    metrics = FakeMetrics()

    response = turn.run(
        state=make_state(),
        session_id="test-session",
        metrics=metrics,  # type: ignore[arg-type]
        tools=[],
        task_turn=1,
        on_text_delta=deltas.append,
    )

    assert deltas == ["Fallback answer"]
    assert response.content == "Fallback answer"
