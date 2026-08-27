import time
from collections.abc import Callable
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
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

from .agent_tool_runner import AgentToolRunner
from .agent_turn import AgentTurn

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
    Jimmy's core execution loop.

    The model is the decision maker.

    Flow:

        ask → act → observe → decide → finish
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
        """
        Run the agent until the user's task is complete
        or the maximum number of turns is reached.
        """

        # Build tool schemas once.
        #
        # Do not rebuild them on every turn.
        tool_schemas = self.tools.schemas()

        while state.turn_count < max_turns:
            # --------------------------------------------
            # Start next reasoning turn
            # --------------------------------------------

            state.next_turn()

            self.session_store.save(
                session_id=session_id,
                state=state,
                status="running",
            )

            # --------------------------------------------
            # Ask the model what to do
            # --------------------------------------------

            response = self.turn.run(
                state=state,
                session_id=session_id,
                metrics=metrics,
                tools=tool_schemas,
                on_event=on_event,
            )

            # --------------------------------------------
            # Save model response
            # --------------------------------------------

            if response.assistant_message:
                state.add_message(response.assistant_message)

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

            # --------------------------------------------
            # No tool call = final answer
            # --------------------------------------------

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

            # --------------------------------------------
            # Execute requested tools
            # --------------------------------------------

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

                # Any tool may explicitly report completion.
                if completed:
                    result = self._completion_message(state)

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

        # --------------------------------------------
        # Maximum turns
        # --------------------------------------------

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

    def _completion_message(
        self,
        state: SessionState,
    ) -> str:
        """
        Return the most recent useful tool result.

        Tool messages are the source of truth for tool completion.
        """

        for message in reversed(state.messages):
            if message.get("role") == "tool":
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
        metrics.finish(time.monotonic() - started_at)

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
                    elapsed=(time.monotonic() - started_at),
                    message=message,
                )
            )
