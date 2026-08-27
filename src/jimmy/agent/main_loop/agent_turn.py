from __future__ import annotations

import time
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.context.context import ContextManager
from jimmy.llm.base import LLMProvider, LLMResponse
from jimmy.llm.errors import LLMProviderError
from jimmy.observability.metrics import (
    LLMUsage,
    Observability,
    RunMetrics,
)
from jimmy.state.session import SessionState


class AgentTurn:
    """Handles one LLM reasoning turn."""

    MAX_RETRIES = 3
    RETRY_DELAYS = (
        5.0,
        10.0,
        20.0,
    )

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
        task_turn: int,
        on_event=None,
    ) -> LLMResponse:
        started_at = time.monotonic()

        def emit(event: AgentEvent) -> None:
            if on_event is not None:
                on_event(event)

        emit(
            AgentEvent(
                kind="turn_start",
                turn=task_turn,
            )
        )

        context = self.context_manager.prepare(
            state.messages,
        )

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = self.llm.chat(
                    messages=context,
                    tools=tools,
                )

                elapsed = time.monotonic() - started_at

                usage = LLMUsage.from_dict(getattr(response, "usage", None))

                model_name = getattr(
                    self.llm,
                    "model",
                    type(self.llm).__name__,
                )

                metrics.turns = task_turn

                metrics.add_llm_usage(
                    model=model_name,
                    usage=usage,
                )

                self.observability.record(
                    "llm_call",
                    {
                        "session_id": session_id,
                        "task_turn": task_turn,
                        "session_turn": state.turn_count,
                        "attempt": attempt + 1,
                        "model": model_name,
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "total_tokens": usage.total_tokens,
                        "cost_usd": usage.cost_usd,
                        "elapsed_seconds": elapsed,
                    },
                )

                emit(
                    AgentEvent(
                        kind="turn_end",
                        turn=task_turn,
                        elapsed=elapsed,
                        message=(
                            "final response"
                            if not response.tool_calls
                            else (f"{len(response.tool_calls)} tool call(s)")
                        ),
                    )
                )

                return response

            except LLMProviderError as exc:
                retryable = bool(
                    getattr(
                        exc,
                        "retryable",
                        False,
                    )
                )

                # Do not retry permanent errors.
                if not retryable or attempt >= self.MAX_RETRIES:
                    elapsed = time.monotonic() - started_at

                    self.observability.record(
                        "llm_error",
                        {
                            "session_id": session_id,
                            "task_turn": task_turn,
                            "session_turn": state.turn_count,
                            "attempt": attempt + 1,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                            "code": getattr(
                                exc,
                                "code",
                                None,
                            ),
                        },
                    )

                    emit(
                        AgentEvent(
                            kind="error",
                            turn=task_turn,
                            elapsed=elapsed,
                            message=str(exc),
                        )
                    )

                    raise

                delay = self.RETRY_DELAYS[attempt]

                self.observability.record(
                    "llm_retry",
                    {
                        "session_id": session_id,
                        "task_turn": task_turn,
                        "session_turn": state.turn_count,
                        "attempt": attempt + 1,
                        "delay_seconds": delay,
                        "reason": str(exc),
                    },
                )

                # Existing event model has no "status" event.
                # Keep retry internal; the TUI remains stable.
                time.sleep(delay)

            except Exception as exc:
                elapsed = time.monotonic() - started_at

                message = f"❌ LLM request failed.\n{type(exc).__name__}: {exc}"

                self.observability.record(
                    "llm_error",
                    {
                        "session_id": session_id,
                        "task_turn": task_turn,
                        "session_turn": state.turn_count,
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )

                emit(
                    AgentEvent(
                        kind="error",
                        turn=task_turn,
                        elapsed=elapsed,
                        message=message,
                    )
                )

                raise RuntimeError(message) from exc

        raise RuntimeError("LLM retry loop ended unexpectedly.")
