import time
from collections.abc import Callable
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
from jimmy.agent.main_loop.agent_tool_runner import (
    AgentToolRunner,
)
from jimmy.agent.main_loop.agent_turn import (
    AgentTurn,
)
from jimmy.agent.observer import Observer
from jimmy.agent.recovery import RecoveryManager
from jimmy.context.context import ContextManager
from jimmy.llm.base import LLMProvider
from jimmy.observability.metrics import (
    Observability,
    RunMetrics,
)
from jimmy.permissions.manager import PermissionManager
from jimmy.session.store import SessionStore
from jimmy.state.session import SessionState
from jimmy.tools.registry import ToolRegistry

EventHandler = Callable[
    [AgentEvent],
    None,
]

PermissionHandler = Callable[
    [str, str, dict[str, Any]],
    bool,
]


class AgentMainLoop:
    """
    Jimmy's core decision loop.

    ask → execute → observe → continue/done
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        executor: ToolExecutor,
        observer: Observer,
        recovery: RecoveryManager,
        context_manager: ContextManager,
        permissions: PermissionManager,
        session_store: SessionStore,
        observability: Observability,
    ) -> None:
        self.session_store = session_store

        self.turn = AgentTurn(
            llm=llm,
            context_manager=context_manager,
            observability=observability,
        )

        self.tool_runner = AgentToolRunner(
            tools=tools,
            executor=executor,
            observer=observer,
            recovery=recovery,
            permissions=permissions,
            observability=observability,
        )

        self.tools = tools
        self.observability = observability

    def run(
        self,
        state: SessionState,
        session_id: str,
        max_turns: int,
        started_at: float,
        metrics: RunMetrics,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
    ) -> str:
        tool_schemas = self.tools.schemas()

        while state.turn_count < max_turns:
            state.next_turn()

            self.session_store.save(
                session_id=session_id,
                state=state,
                status="running",
            )

            response = self.turn.run(
                state=state,
                session_id=session_id,
                metrics=metrics,
                tools=tool_schemas,
                on_event=on_event,
            )

            if response.assistant_message:
                state.add_message(response.assistant_message)

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

            # No tool call means Jimmy has finished.
            if not response.tool_calls:
                result = response.content or ""

                metrics.finish(time.monotonic() - started_at)

                self.observability.record_run(
                    metrics,
                    status="completed",
                )

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="completed",
                )

                if on_event is not None:
                    on_event(
                        AgentEvent(
                            kind="complete",
                            turn=state.turn_count,
                            elapsed=(time.monotonic() - started_at),
                            message=result,
                        )
                    )

                return result

            # Execute the model's requested tools.
            for tool_call in response.tool_calls:
                completed = self.tool_runner.run(
                    state=state,
                    session_id=session_id,
                    metrics=metrics,
                    tool_call=tool_call,
                    on_event=on_event,
                    on_permission=on_permission,
                )

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

                # Any tool can finish the task.
                if completed:
                    result = (
                        state.messages[-1].get(
                            "content",
                            "Task completed.",
                        )
                        if state.messages
                        else "Task completed."
                    )

                    metrics.finish(time.monotonic() - started_at)

                    self.observability.record_run(
                        metrics,
                        status="completed",
                    )

                    self.session_store.save(
                        session_id=session_id,
                        state=state,
                        status="completed",
                    )

                    if on_event is not None:
                        on_event(
                            AgentEvent(
                                kind="complete",
                                turn=state.turn_count,
                                elapsed=(time.monotonic() - started_at),
                                message=result,
                            )
                        )

                    return result

        message = f"❌ Jimmy stopped because the maximum of {max_turns} turns was reached."

        metrics.failures += 1

        self.observability.record(
            "error",
            {
                "session_id": session_id,
                "turn": state.turn_count,
                "error": message,
                "error_type": "MaxTurnsExceeded",
            },
        )

        metrics.finish(time.monotonic() - started_at)

        self.observability.record_run(
            metrics,
            status="failed",
        )

        self.session_store.save(
            session_id=session_id,
            state=state,
            status="failed",
        )

        if on_event is not None:
            on_event(
                AgentEvent(
                    kind="error",
                    turn=state.turn_count,
                    elapsed=(time.monotonic() - started_at),
                    message=message,
                )
            )

        raise RuntimeError(message)
