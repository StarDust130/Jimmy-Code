import time
from collections.abc import Callable
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
from jimmy.agent.main_loop.agent_tool_runner import (
    AgentToolRunner,
)
from jimmy.agent.main_loop.agent_turn import AgentTurn
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
    Core Jimmy decision loop.

    One cycle:

        ask → execute → observe → decide

    The LLM is responsible for choosing the next action.
    Runtime code is responsible for enforcing correctness.
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
        self.tools = tools
        self.session_store = session_store
        self.observability = observability

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

            # Save exactly what the model returned.
            if response.assistant_message:
                state.add_message(response.assistant_message)

            # ------------------------------------------------
            # Final text response
            # ------------------------------------------------

            if not response.tool_calls:
                result = response.content or ""

                self._finish(
                    state=state,
                    session_id=session_id,
                    metrics=metrics,
                    started_at=started_at,
                    status="completed",
                    on_event=on_event,
                    message=result,
                )

                return result

            # ------------------------------------------------
            # Execute tool calls requested by the model
            # ------------------------------------------------

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

                # Generic completion:
                # ANY tool can end the task.
                if completed:
                    result = self._last_tool_result(state)

                    self._finish(
                        state=state,
                        session_id=session_id,
                        metrics=metrics,
                        started_at=started_at,
                        status="completed",
                        on_event=on_event,
                        message=result,
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

        self._finish(
            state=state,
            session_id=session_id,
            metrics=metrics,
            started_at=started_at,
            status="failed",
            on_event=on_event,
            message=message,
        )

        raise RuntimeError(message)

    @staticmethod
    def _last_tool_result(
        state: SessionState,
    ) -> str:
        for message in reversed(state.messages):
            if message.get("role") != "tool":
                continue

            content = str(
                message.get(
                    "content",
                    "",
                )
                or ""
            ).strip()

            if content:
                return content

        return "Task completed."

    def _finish(
        self,
        state: SessionState,
        session_id: str,
        metrics: RunMetrics,
        started_at: float,
        status: str,
        on_event: EventHandler | None,
        message: str,
    ) -> None:
        elapsed = time.monotonic() - started_at

        metrics.finish(elapsed)

        self.observability.record_run(
            metrics,
            status=status,
        )

        self.session_store.save(
            session_id=session_id,
            state=state,
            status=status,
        )

        if on_event is not None:
            on_event(
                AgentEvent(
                    kind=("complete" if status == "completed" else "error"),
                    turn=state.turn_count,
                    elapsed=elapsed,
                    message=message,
                )
            )
