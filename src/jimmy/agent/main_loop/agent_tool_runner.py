from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
from jimmy.agent.main_loop.agent_progress import AgentProgress
from jimmy.agent.main_loop.agent_tool_guard import ToolGuard
from jimmy.agent.observer import Observer
from jimmy.agent.recovery import RecoveryManager
from jimmy.observability.metrics import Observability, RunMetrics
from jimmy.permissions.errors import PermissionRequired
from jimmy.permissions.manager import (
    PermissionAction,
    PermissionManager,
)
from jimmy.state.session import SessionState
from jimmy.tools.registry import ToolRegistry
from jimmy.utils.limits import truncate_output

EventHandler = Callable[[AgentEvent], None]

PermissionHandler = Callable[
    [str, str, dict[str, Any]],
    bool,
]


class AgentToolRunner:
    """
    Executes one model-requested tool call.

    Pipeline:

        tool guard
        -> progress guard
        -> tool lookup
        -> permission
        -> execution
        -> observation
        -> recovery
        -> state update
    """

    def __init__(
        self,
        tools: ToolRegistry,
        executor: ToolExecutor,
        observer: Observer,
        recovery: RecoveryManager,
        permissions: PermissionManager,
        observability: Observability,
        workspace: Path,
    ) -> None:
        self.tools = tools
        self.executor = executor
        self.observer = observer
        self.recovery = recovery
        self.permissions = permissions
        self.observability = observability

        self.guard = ToolGuard(
            workspace=workspace,
        )

    def run(
        self,
        state: SessionState,
        session_id: str,
        metrics: RunMetrics,
        tool_call: Any,
        progress: AgentProgress,
        task_turn: int,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
    ) -> bool:
        started_at = time.monotonic()

        def emit(event: AgentEvent) -> None:
            if on_event is not None:
                on_event(event)

        tool_name = str(
            tool_call.name,
        ).strip()

        arguments = dict(
            tool_call.arguments or {},
        )

        emit(
            AgentEvent(
                kind="tool_start",
                turn=task_turn,
                tool_name=tool_name,
                arguments=arguments,
            ),
        )

        # ======================================================
        # 1. TOOL POLICY
        # ======================================================

        guard = self.guard.check(
            tool_name=tool_name,
            arguments=arguments,
            state=state,
        )

        if not guard.allowed:
            reason = guard.reason or "Tool action was rejected."

            self._save_tool_message(
                state=state,
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                content=(
                    f"Tool rejected by runtime.\nReason: {reason}\nChoose a valid tool/action."
                ),
            )

            self.observability.record(
                "tool_policy_rejection",
                {
                    "session_id": session_id,
                    "task_turn": task_turn,
                    "tool": tool_name,
                    "reason": reason,
                },
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=0.0,
                    message="blocked",
                ),
            )

            # The tool never executed.
            # Do not record an execution failure.
            return False

        # ======================================================
        # 2. PROGRESS GUARD
        # ======================================================

        allowed, reason = progress.can_run(
            tool_name,
            arguments,
        )

        if not allowed:
            message = reason or "Repeated action detected."

            self._save_tool_message(
                state=state,
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                content=(
                    "Action blocked to prevent an execution loop.\n"
                    f"{message}\n"
                    "Choose a different approach."
                ),
            )

            self.observability.record(
                "progress_guard_rejection",
                {
                    "session_id": session_id,
                    "task_turn": task_turn,
                    "tool": tool_name,
                    "reason": message,
                },
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=0.0,
                    message="blocked",
                ),
            )

            raise RuntimeError(message)

        # ======================================================
        # 3. TOOL LOOKUP
        # ======================================================

        try:
            tool = self.tools.get(tool_name)
        except Exception:
            error = RuntimeError(f"Unknown tool '{tool_name}'.")

            progress.record(
                tool_name,
                arguments,
                success=False,
                changed_workspace=False,
            )

            return self._handle_exception(
                state=state,
                session_id=session_id,
                metrics=metrics,
                tool_call=tool_call,
                tool_name=tool_name,
                error=error,
                started_at=started_at,
                task_turn=task_turn,
                on_event=on_event,
            )

        # ======================================================
        # 4. PERMISSION
        # ======================================================

        permission = self.permissions.check(
            tool,
        )

        if permission.action == PermissionAction.DENY:
            elapsed = time.monotonic() - started_at

            message = f"Permission denied for '{tool_name}'.\n{permission.reason}"

            self._save_tool_message(
                state=state,
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                content=message,
            )

            self.observability.record(
                "tool_permission_denied",
                {
                    "session_id": session_id,
                    "task_turn": task_turn,
                    "tool": tool_name,
                    "reason": permission.reason,
                },
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=elapsed,
                    message="denied",
                ),
            )

            # Permission rejection is not a tool execution failure.
            return False

        if permission.action == PermissionAction.ASK:
            if on_permission is None:
                raise PermissionRequired(
                    tool_name=tool_name,
                    reason=permission.reason,
                    arguments=arguments,
                )

            approved = on_permission(
                tool_name,
                permission.reason,
                arguments,
            )

            if not approved:
                elapsed = time.monotonic() - started_at

                self._save_tool_message(
                    state=state,
                    tool_call_id=tool_call.id,
                    tool_name=tool_name,
                    content=(
                        "Permission denied by the user. "
                        "Do not retry unless the user explicitly "
                        "requests the action again."
                    ),
                )

                emit(
                    AgentEvent(
                        kind="tool_end",
                        turn=task_turn,
                        tool_name=tool_name,
                        elapsed=elapsed,
                        message="denied",
                    ),
                )

                return False

        # ======================================================
        # 5. EXECUTE
        # ======================================================

        try:
            tool_result = self.executor.execute(
                tool_name=tool_name,
                arguments=arguments,
            )
        except Exception as exc:
            return self._handle_exception(
                state=state,
                session_id=session_id,
                metrics=metrics,
                tool_call=tool_call,
                tool_name=tool_name,
                error=exc,
                started_at=started_at,
                task_turn=task_turn,
                on_event=on_event,
            )

        # ======================================================
        # 6. NORMALIZE OUTPUT
        # ======================================================

        if tool_result.success:
            output = truncate_output(
                tool_result.output or "",
            )
        else:
            output = truncate_output(
                (
                    f"Tool '{tool_name}' failed.\n"
                    f"Error type: "
                    f"{tool_result.error_type}\n"
                    f"Error: "
                    f"{tool_result.error or 'Unknown error'}"
                ),
            )

        elapsed = time.monotonic() - started_at

        metrics.add_tool_time(
            tool_name=tool_name,
            elapsed=elapsed,
        )

        # ======================================================
        # 7. OBSERVE
        # ======================================================

        if tool_result.success:
            observation = self.observer.observe_success(
                tool_name=tool_name,
                result=output,
            )
        else:
            observation = self.observer.observe_failure(
                tool_name=tool_name,
                error=RuntimeError(
                    tool_result.error or "Unknown tool error.",
                ),
            )

        # ======================================================
        # 8. ACTUAL FAILURE
        # ======================================================

        if not tool_result.success:
            metrics.failures += 1

            failure = RuntimeError(
                tool_result.error or "Unknown tool error.",
            )

            recovery = self.recovery.recover(
                failure,
            )

            # IMPORTANT:
            # Send the actual error AND recovery guidance
            # back to the LLM.
            tool_message = f"{observation.result}\n\nRecovery guidance: {recovery.message}"

            self._save_tool_message(
                state=state,
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                content=tool_message,
            )

            progress.record(
                tool_name,
                arguments,
                success=False,
                changed_workspace=False,
            )

            self.observability.record(
                "tool_failure",
                {
                    "session_id": session_id,
                    "task_turn": task_turn,
                    "tool": tool_name,
                    "error": failure.__class__.__name__,
                    "error_message": str(failure),
                    "recovery_category": recovery.category.value,
                    "retryable": recovery.retry,
                },
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=elapsed,
                    message="error",
                ),
            )

            if not recovery.should_continue:
                raise RuntimeError(
                    recovery.message,
                ) from failure

            return False

        # ======================================================
        # 9. SUCCESS
        # ======================================================

        self._save_tool_message(
            state=state,
            tool_call_id=tool_call.id,
            tool_name=tool_name,
            content=observation.result,
        )

        self.observability.record(
            "tool_success",
            {
                "session_id": session_id,
                "task_turn": task_turn,
                "tool": tool_name,
                "elapsed_seconds": elapsed,
            },
        )

        emit(
            AgentEvent(
                kind="tool_end",
                turn=task_turn,
                tool_name=tool_name,
                elapsed=elapsed,
                message="ok",
            ),
        )

        progress.record(
            tool_name,
            arguments,
            success=True,
            changed_workspace=not tool.metadata.read_only,
        )

        return bool(
            (tool_result.metadata or {}).get(
                "task_complete",
                False,
            )
        )

    # ==========================================================
    # EXCEPTION PATH
    # ==========================================================

    def _handle_exception(
        self,
        *,
        state: SessionState,
        session_id: str,
        metrics: RunMetrics,
        tool_call: Any,
        tool_name: str,
        error: Exception,
        started_at: float,
        task_turn: int,
        on_event: EventHandler | None,
    ) -> bool:
        elapsed = time.monotonic() - started_at

        metrics.failures += 1

        recovery = self.recovery.recover(
            error,
        )

        message = (
            f"Tool '{tool_name}' failed.\n"
            f"{type(error).__name__}: {error}\n\n"
            f"Recovery guidance: {recovery.message}"
        )

        self._save_tool_message(
            state=state,
            tool_call_id=tool_call.id,
            tool_name=tool_name,
            content=message,
        )

        self.observability.record(
            "tool_exception",
            {
                "session_id": session_id,
                "task_turn": task_turn,
                "tool": tool_name,
                "error_type": type(error).__name__,
                "error": str(error),
                "recovery_category": recovery.category.value,
                "retryable": recovery.retry,
            },
        )

        if on_event is not None:
            on_event(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=elapsed,
                    message="error",
                )
            )

        if not recovery.should_continue:
            raise RuntimeError(
                recovery.message,
            ) from error

        return False

    # ==========================================================
    # STATE HELPER
    # ==========================================================

    @staticmethod
    def _save_tool_message(
        *,
        state: SessionState,
        tool_call_id: str,
        tool_name: str,
        content: str,
    ) -> None:
        state.add_message(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "content": content,
            }
        )
