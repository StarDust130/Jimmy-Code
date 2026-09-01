from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any, Protocol, cast

from jimmy.agent.events import AgentEvent
from jimmy.agent.main_loop.agent_progress import AgentProgress
from jimmy.context.context import ContextManager
from jimmy.llm.base import LLMResponse
from jimmy.llm.errors import LLMProviderError
from jimmy.llm.streaming import LLMStreamChunk
from jimmy.observability.metrics import (
    LLMUsage,
    Observability,
    RunMetrics,
)
from jimmy.state.session import SessionState


TextDeltaHandler = Callable[[str], None]
AgentEventHandler = Callable[[AgentEvent], None]

StreamItem = str | LLMStreamChunk | LLMResponse


class StreamMethod(Protocol):
    def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamItem]: ...


class ChatMethod(Protocol):
    def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...


class AgentTurn:
    """
    Run one LLM decision.

    Native streaming is preferred.
    Providers without usable streaming fall back to chat.
    """

    MAX_RETRIES = 3
    RETRY_DELAYS = (
        5.0,
        10.0,
        20.0,
    )

    def __init__(
        self,
        llm: Any,
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
        task_turn: int = 1,
        progress: AgentProgress | None = None,
        on_event: AgentEventHandler | None = None,
        on_text_delta: TextDeltaHandler | None = None,
    ) -> LLMResponse:
        started_at = time.monotonic()

        def emit(
            event: AgentEvent,
        ) -> None:
            if on_event is not None:
                on_event(event)

        def emit_delta(
            text: str,
        ) -> None:
            if text and on_text_delta is not None:
                on_text_delta(text)

        emit(
            AgentEvent(
                kind="turn_start",
                turn=task_turn,
            ),
        )

        if progress is not None:
            progress.start_turn(
                task_turn,
            )

        context = self.context_manager.prepare(
            state.messages,
        )

        stream_method_raw = getattr(
            self.llm,
            "stream",
            None,
        )

        stream_method: StreamMethod | None = (
            cast(
                StreamMethod,
                stream_method_raw,
            )
            if callable(stream_method_raw)
            else None
        )

        chat_method = cast(
            ChatMethod,
            self.llm.chat,
        )

        for attempt in range(
            self.MAX_RETRIES + 1,
        ):
            emitted_text = False

            def emit_attempt_delta(
                text: str,
            ) -> None:
                nonlocal emitted_text

                if text:
                    emitted_text = True

                emit_delta(
                    text,
                )

            try:
                # ==================================================
                # STREAMING
                # ==================================================

                if stream_method is not None:
                    response = self._run_stream(
                        stream_method=stream_method,
                        context=context,
                        tools=tools,
                        on_text_delta=emit_attempt_delta,
                    )

                    # Some lightweight providers expose a stream
                    # method only because it exists on a base class,
                    # but return no useful stream data.
                    #
                    # In that case use normal chat.
                    if (
                        not response.content
                        and not response.tool_calls
                        and not response.assistant_message
                    ):
                        response = chat_method(
                            messages=context,
                            tools=tools,
                        )

                        if response.content:
                            emit_attempt_delta(
                                response.content,
                            )

                # ==================================================
                # CHAT
                # ==================================================

                else:
                    response = chat_method(
                        messages=context,
                        tools=tools,
                    )

                    if response.content:
                        emit_attempt_delta(
                            response.content,
                        )

                elapsed = (
                    time.monotonic()
                    - started_at
                )

                usage = LLMUsage.from_dict(
                    getattr(
                        response,
                        "usage",
                        None,
                    ),
                )

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
                        "streaming": stream_method is not None,
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
                            else (
                                f"{len(response.tool_calls)} "
                                "tool call(s)"
                            )
                        ),
                    ),
                )

                return response

            except LLMProviderError as exc:
                retryable = bool(
                    getattr(
                        exc,
                        "retryable",
                        False,
                    ),
                )

                if emitted_text:
                    elapsed = (
                        time.monotonic()
                        - started_at
                    )

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
                            "after_stream_output": True,
                        },
                    )

                    emit(
                        AgentEvent(
                            kind="error",
                            turn=task_turn,
                            elapsed=elapsed,
                            message=str(exc),
                        ),
                    )

                    raise

                if (
                    not retryable
                    or attempt >= self.MAX_RETRIES
                ):
                    elapsed = (
                        time.monotonic()
                        - started_at
                    )

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
                        ),
                    )

                    raise

                delay = self.RETRY_DELAYS[
                    attempt
                ]

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

                time.sleep(
                    delay,
                )

            except Exception as exc:
                elapsed = (
                    time.monotonic()
                    - started_at
                )

                message = (
                    "❌ LLM request failed.\n"
                    f"{type(exc).__name__}: {exc}"
                )

                self.observability.record(
                    "llm_error",
                    {
                        "session_id": session_id,
                        "task_turn": task_turn,
                        "session_turn": state.turn_count,
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "after_stream_output": emitted_text,
                    },
                )

                emit(
                    AgentEvent(
                        kind="error",
                        turn=task_turn,
                        elapsed=elapsed,
                        message=message,
                    ),
                )

                raise RuntimeError(
                    message,
                ) from exc

        raise RuntimeError(
            "LLM retry loop ended unexpectedly.",
        )

    # ============================================================
    # STREAM CONSUMER
    # ============================================================

    @staticmethod
    def _run_stream(
        stream_method: StreamMethod,
        context: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        on_text_delta: TextDeltaHandler,
    ) -> LLMResponse:
        """
        Consume a provider-neutral stream.

        A provider may:
        - emit text chunks only
        - emit LLMStreamChunk objects
        - emit a final LLMResponse
        - emit a combination
        """

        final_response: LLMResponse | None = None

        streamed_text: list[str] = []

        stream = stream_method(
            messages=context,
            tools=tools,
        )

        for item in stream:
            # ==================================================
            # STANDARD CHUNK
            # ==================================================

            if isinstance(
                item,
                LLMStreamChunk,
            ):
                if item.text:
                    streamed_text.append(
                        item.text,
                    )

                    on_text_delta(
                        item.text,
                    )

                if item.response is not None:
                    final_response = (
                        item.response
                    )

                continue

            # ==================================================
            # SIMPLE STRING
            # ==================================================

            if isinstance(
                item,
                str,
            ):
                if item:
                    streamed_text.append(
                        item,
                    )

                    on_text_delta(
                        item,
                    )

                continue

            # ==================================================
            # FINAL RESPONSE
            # ==================================================

            if isinstance(
                item,
                LLMResponse,
            ):
                final_response = item
                continue

            # ==================================================
            # COMPATIBILITY OBJECT
            # ==================================================

            text = getattr(
                item,
                "text",
                None,
            )

            if isinstance(
                text,
                str,
            ) and text:
                streamed_text.append(
                    text,
                )

                on_text_delta(
                    text,
                )

            response = getattr(
                item,
                "response",
                None,
            )

            if isinstance(
                response,
                LLMResponse,
            ):
                final_response = response

        # ==================================================
        # PROVIDER GAVE COMPLETE RESPONSE
        # ==================================================

        if final_response is not None:
            return final_response

        # ==================================================
        # STREAM HAD TEXT BUT NO FINAL OBJECT
        # ==================================================

        content = "".join(
            streamed_text,
        )

        if content:
            return LLMResponse(
                content=content,
                tool_calls=[],
                assistant_message={
                    "role": "assistant",
                    "content": content,
                },
                usage=None,
            )

        # ==================================================
        # EMPTY STREAM
        #
        # Return an unmistakably empty response so caller
        # can fall back to chat.
        # ==================================================

        return LLMResponse(
            content="",
            tool_calls=[],
            assistant_message=None,
            usage=None,
        )