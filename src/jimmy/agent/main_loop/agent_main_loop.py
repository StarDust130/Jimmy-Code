from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
from jimmy.agent.main_loop.agent_progress import AgentProgress
from jimmy.agent.main_loop.agent_tool_runner import AgentToolRunner
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

TextDeltaHandler = Callable[
    [str],
    None,
]


class AgentMainLoop:
    """
    Core Jimmy agent loop.

    Flow:

        ask
        ↓
        choose tools
        ↓
        execute
        ↓
        observe
        ↓
        decide
        ↓
        finish

    `task_turn` is local to one user request.
    `state.turn_count` remains the persistent session counter.
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
        workspace: Any,
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
            workspace=workspace,
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
        on_text_delta: TextDeltaHandler | None = None,
    ) -> str:
        """
        Run one user task.

        The task has its own turn budget.
        """

        tool_schemas = self.tools.schemas()

        # New progress state for this task only.
        progress = AgentProgress()

        # IMPORTANT:
        # Do NOT use state.turn_count for the task budget.
        task_turn = 0

        while task_turn < max_turns:
            task_turn += 1

            # Persistent session turn.
            state.next_turn()

            self.session_store.save(
                session_id=session_id,
                state=state,
                status="running",
            )

            # --------------------------------------------------
            # LLM DECISION
            # --------------------------------------------------

            response = self.turn.run(
                state=state,
                session_id=session_id,
                metrics=metrics,
                tools=tool_schemas,
                task_turn=task_turn,
                on_event=on_event,
                on_text_delta=on_text_delta,
            )

            # --------------------------------------------------
            # SAVE ASSISTANT MESSAGE
            # --------------------------------------------------

            if response.assistant_message:
                state.add_message(
                    response.assistant_message,
                )

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

            # --------------------------------------------------
            # FINAL TEXT RESPONSE
            # --------------------------------------------------

            if not response.tool_calls:
                result = response.content or ""

                return self._complete(
                    state=state,
                    session_id=session_id,
                    metrics=metrics,
                    started_at=started_at,
                    task_turn=task_turn,
                    message=result,
                    on_event=on_event,
                )

            # --------------------------------------------------
            # EXECUTE MODEL TOOL CALLS
            # --------------------------------------------------

            for tool_call in response.tool_calls:
                completed = self.tool_runner.run(
                    state=state,
                    session_id=session_id,
                    metrics=metrics,
                    tool_call=tool_call,
                    progress=progress,
                    task_turn=task_turn,
                    on_event=on_event,
                    on_permission=on_permission,
                )

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

                # A tool may explicitly say:
                #
                # task_complete=True
                #
                # Only then should the loop finish immediately.
                if completed:
                    result = self._last_tool_result(
                        state,
                    )

                    return self._complete(
                        state=state,
                        session_id=session_id,
                        metrics=metrics,
                        started_at=started_at,
                        task_turn=task_turn,
                        message=result,
                        on_event=on_event,
                    )

            # If tools were executed and none marked completion,
            # go back to the LLM for the next decision.
            #
            # This is important for tasks such as:
            #
            #     commit a.py, b.py, c.py one by one
            #
            # where one tool call may only complete part of
            # the user's request.

        # ------------------------------------------------------
        # TASK TURN LIMIT
        # ------------------------------------------------------

        message = f"❌ Jimmy stopped because this task reached the maximum of {max_turns} turns."

        metrics.failures += 1

        self.observability.record(
            "error",
            {
                "session_id": session_id,
                "task_turn": task_turn,
                "session_turn": state.turn_count,
                "error": message,
                "error_type": "MaxTaskTurnsExceeded",
            },
        )

        self._finish(
            state=state,
            session_id=session_id,
            metrics=metrics,
            started_at=started_at,
            status="failed",
            on_event=on_event,
            task_turn=task_turn,
            message=message,
            started_at_monotonic=started_at,
        )

        raise RuntimeError(
            message,
        )

    # ==========================================================
    # COMPLETION
    # ==========================================================

    def _complete(
        self,
        state: SessionState,
        session_id: str,
        metrics: RunMetrics,
        started_at: float,
        task_turn: int,
        message: str,
        on_event: EventHandler | None,
    ) -> str:
        self._finish(
            state=state,
            session_id=session_id,
            metrics=metrics,
            started_at=started_at,
            status="completed",
            on_event=on_event,
            task_turn=task_turn,
            message=message,
            started_at_monotonic=started_at,
        )

        return message

    # ==========================================================
    # LAST TOOL RESULT
    # ==========================================================

    @staticmethod
    def _last_tool_result(
        state: SessionState,
    ) -> str:
        """
        Return the latest tool observation.
        """

        for message in reversed(
            state.messages,
        ):
            if message.get("role") != "tool":
                continue

            content = str(
                message.get(
                    "content",
                    "",
                )
                or "",
            ).strip()

            if content:
                return content

        return "Task completed."

    # ==========================================================
    # FINISH
    # ==========================================================

    def _finish(
        self,
        *,
        state: SessionState,
        session_id: str,
        metrics: RunMetrics,
        started_at: float,
        status: str,
        on_event: EventHandler | None,
        task_turn: int,
        message: str,
        started_at_monotonic: float,
    ) -> None:
        # `started_at_monotonic` is kept explicit so this method
        # remains easy to follow and avoids accidentally mixing
        # wall-clock time with monotonic time.
        del started_at

        elapsed = time.monotonic() - started_at_monotonic

        metrics.finish(
            elapsed,
        )

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
                    turn=task_turn,
                    elapsed=elapsed,
                    message=message,
                ),
            )
