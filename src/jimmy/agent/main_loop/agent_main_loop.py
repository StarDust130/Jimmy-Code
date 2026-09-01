from __future__ import annotations

import re
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
from jimmy.agent.task_state import TaskState
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


EventHandler = Callable[[AgentEvent], None]

PermissionHandler = Callable[
    [str, str, dict[str, Any]],
    bool,
]

TextDeltaHandler = Callable[[str], None]


class AgentMainLoop:
    """
    Core Jimmy agent loop.

    Flow:

        understand
            ↓
        model decision
            ↓
        execute tool(s)
            ↓
        observe real result
            ↓
        model decides again
            ↓
        verify when appropriate
            ↓
        finish

    The model decides what to do.
    Runtime code verifies hard facts.
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
        progress: AgentProgress | None = None,
        task_state: TaskState | None = None,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
        on_text_delta: TextDeltaHandler | None = None,
    ) -> str:
        """
        Run one user task.

        `task_turn` is local to this task.
        `state.turn_count` remains the persistent session counter.
        """

        tool_schemas = self.tools.schemas()

        if progress is None:
            progress = AgentProgress()

        task_turn = 0

        while task_turn < max_turns:
            task_turn += 1

            state.next_turn()

            self.session_store.save(
                session_id=session_id,
                state=state,
                status="running",
            )

            # ==================================================
            # MODEL DECISION
            # ==================================================

            response = self.turn.run(
                state=state,
                session_id=session_id,
                metrics=metrics,
                tools=tool_schemas,
                task_turn=task_turn,
                progress=progress,
                on_event=on_event,
                on_text_delta=on_text_delta,
            )

            # ==================================================
            # SAVE MODEL RESPONSE
            # ==================================================

            if response.assistant_message:
                state.add_message(
                    response.assistant_message,
                )

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

            # ==================================================
            # FINAL MODEL TEXT
            # ==================================================

            if not response.tool_calls:
                result = (
                    response.content or ""
                ).strip()

                # --------------------------------------------------
                # HARD VERIFICATION FAILURE
                #
                # This comes from an actual verification command,
                # not from model text.
                # --------------------------------------------------

                if self._last_tool_verification_failed(
                    state,
                ):
                    state.add_message(
                        {
                            "role": "user",
                            "content": (
                                "<verification_failure>\n"
                                "A real verification command failed.\n\n"
                                "The task is NOT verified as complete.\n"
                                "Inspect the actual failure, fix the "
                                "underlying problem, and run the relevant "
                                "verification again before finishing.\n"
                                "</verification_failure>"
                            ),
                        },
                    )

                    self.session_store.save(
                        session_id=session_id,
                        state=state,
                        status="running",
                    )

                    continue

                # --------------------------------------------------
                # FALSE COMPLETION
                #
                # Read-only tasks remain allowed.
                # This only catches a model claiming a mutation
                # happened when runtime saw no successful mutation.
                # --------------------------------------------------

                if self._false_completion(
                    result=result,
                    progress=progress,
                ):
                    state.add_message(
                        {
                            "role": "user",
                            "content": (
                                "<completion_check>\n"
                                "Your previous response claims that "
                                "you changed the workspace, but no "
                                "successful workspace mutation was "
                                "recorded for this task.\n\n"
                                "Do not claim completion yet. Continue "
                                "with the actual requested work, or "
                                "explain the real blocker.\n"
                                "</completion_check>"
                            ),
                        },
                    )

                    self.session_store.save(
                        session_id=session_id,
                        state=state,
                        status="running",
                    )

                    continue

                return self._complete(
                    state=state,
                    session_id=session_id,
                    metrics=metrics,
                    started_at=started_at,
                    task_turn=task_turn,
                    message=result,
                    on_event=on_event,
                )

            # ==================================================
            # EXECUTE TOOL CALLS
            # ==================================================

            completed = False

            # A Gemini function-call response is an atomic batch: every
            # requested call needs a function response before the agent can
            # finish or ask the model for another decision.
            for tool_call in response.tool_calls:
                tool_completed = self.tool_runner.run(
                    state=state,
                    session_id=session_id,
                    metrics=metrics,
                    tool_call=tool_call,
                    progress=progress,
                    task_state=task_state,
                    task_turn=task_turn,
                    on_event=on_event,
                    on_permission=on_permission,
                )

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

                completed = completed or tool_completed

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

        # ======================================================
        # MAX TURN FAILURE
        # ======================================================

        message = (
            "❌ Jimmy stopped because this task reached "
            f"the maximum of {max_turns} turns."
        )

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
        )

        raise RuntimeError(
            message,
        )

    # ==========================================================
    # FALSE COMPLETION
    # ==========================================================

    @staticmethod
    def _claims_workspace_change(
        text: str,
    ) -> bool:
        """
        Detect narrow, explicit claims of workspace mutation.

        This is NOT task classification.
        It is only a consistency check.
        """

        normalized = text.strip().lower()

        if not normalized:
            return False

        patterns = (
            r"\bi\s+fixed\b",
            r"\bi\s+created\b",
            r"\bi\s+added\b",
            r"\bi\s+updated\b",
            r"\bi\s+changed\b",
            r"\bi\s+modified\b",
            r"\bi\s+implemented\b",
            r"\bi\s+removed\b",
            r"\bi\s+deleted\b",
            r"\bi\s+renamed\b",
            r"\bi\s+edited\b",
            r"\bi\s+have\s+fixed\b",
            r"\bi\s+have\s+created\b",
            r"\bi\s+have\s+added\b",
            r"\bi\s+have\s+updated\b",
            r"\bi\s+have\s+changed\b",
            r"\bi\s+have\s+implemented\b",
            (
                r"\bsuccessfully\s+"
                r"(?:fixed|created|added|updated|changed|implemented)\b"
            ),
        )

        return any(
            re.search(
                pattern,
                normalized,
            )
            for pattern in patterns
        )

    @classmethod
    def _false_completion(
        cls,
        *,
        result: str,
        progress: AgentProgress,
    ) -> bool:
        """
        Block a likely false claim only when there was no
        successful workspace mutation.

        Read-only tasks remain valid.
        """

        if not result:
            return False

        # Current AgentProgress tracks the number of successful
        # mutations. Do not depend on a nonexistent property.
        successful_mutations = getattr(
            progress,
            "successful_mutations",
            0,
        )

        if successful_mutations > 0:
            return False

        return cls._claims_workspace_change(
            result,
        )

    # ==========================================================
    # REAL VERIFICATION
    # ==========================================================

    @staticmethod
    def _last_tool_verification_failed(
        state: SessionState,
    ) -> bool:
        """
        Inspect the newest tool observation.

        The marker is generated by AgentToolRunner from the
        actual exit code of a verification command.

        We only inspect the newest tool message. An old failed
        verification must not block a later successful task.
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
                or ""
            )

            return (
                "[verification:failed]"
                in content
            )

        return False

    # ==========================================================
    # COMPLETE
    # ==========================================================

    def _complete(
        self,
        *,
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
        )

        return message

    # ==========================================================
    # LAST TOOL RESULT
    # ==========================================================

    @staticmethod
    def _last_tool_result(
        state: SessionState,
    ) -> str:
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
    ) -> None:
        elapsed = (
            time.monotonic()
            - started_at
        )

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
                    kind=(
                        "complete"
                        if status == "completed"
                        else "error"
                    ),
                    turn=task_turn,
                    elapsed=elapsed,
                    message=message,
                ),
            )
