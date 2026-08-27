import time
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.context.context import ContextManager
from jimmy.llm.base import (
    LLMProvider,
    LLMResponse,
)
from jimmy.llm.errors import LLMProviderError
from jimmy.observability.metrics import (
    LLMUsage,
    Observability,
    RunMetrics,
)
from jimmy.state.session import SessionState


class AgentTurn:
    """Runs exactly one LLM decision."""

    def __init__(
        self,
        llm: LLMProvider,
        context_manager: ContextManager,
        observability: Observability,
    ) -> None:
        self.llm = llm
        self.context_manager = context_manager
        self.observability = observability

    def run(
        self,
        state: SessionState,
        session_id: str,
        metrics: RunMetrics,
        tools: list[dict[str, Any]],
        on_event=None,
    ) -> LLMResponse:
        started_at = time.monotonic()
        turn = state.turn_count

        def emit(event: AgentEvent) -> None:
            if on_event is not None:
                on_event(event)

        emit(
            AgentEvent(
                kind="turn_start",
                turn=turn,
            )
        )

        try:
            # ContextManager is allowed to compress only when needed.
            context = self.context_manager.prepare(state.messages)

            response = self.llm.chat(
                messages=context,
                tools=tools,
            )

        except LLMProviderError as exc:
            elapsed = time.monotonic() - started_at

            metrics.failures += 1

            self.observability.record(
                "error",
                {
                    "session_id": session_id,
                    "turn": turn,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

            emit(
                AgentEvent(
                    kind="error",
                    turn=turn,
                    elapsed=elapsed,
                    message=str(exc),
                )
            )

            raise

        except Exception as exc:
            elapsed = time.monotonic() - started_at

            metrics.failures += 1

            message = f"❌ LLM request failed.\n{type(exc).__name__}: {exc}"

            self.observability.record(
                "error",
                {
                    "session_id": session_id,
                    "turn": turn,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

            emit(
                AgentEvent(
                    kind="error",
                    turn=turn,
                    elapsed=elapsed,
                    message=message,
                )
            )

            raise RuntimeError(message) from exc

        # --------------------------------------------
        # Usage / observability
        # --------------------------------------------

        elapsed = time.monotonic() - started_at

        usage = LLMUsage.from_dict(
            getattr(
                response,
                "usage",
                None,
            )
        )

        model_name = getattr(
            self.llm,
            "model",
            type(self.llm).__name__,
        )

        metrics.turns = turn

        metrics.add_llm_usage(
            model=model_name,
            usage=usage,
        )

        self.observability.record(
            "llm_call",
            {
                "session_id": session_id,
                "turn": turn,
                "model": model_name,
                "input_tokens": (usage.input_tokens),
                "output_tokens": (usage.output_tokens),
                "total_tokens": (usage.total_tokens),
                "cost_usd": (usage.cost_usd),
                "elapsed_seconds": elapsed,
            },
        )

        emit(
            AgentEvent(
                kind="turn_end",
                turn=turn,
                elapsed=elapsed,
                message=(
                    "final response"
                    if not response.tool_calls
                    else (f"{len(response.tool_calls)} tool call(s)")
                ),
            )
        )

        return response
