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
from jimmy.observability.metrics import (
    Observability,
    RunMetrics,
)
from jimmy.permissions.errors import PermissionRequired
from jimmy.permissions.manager import (
    PermissionAction,
    PermissionManager,
)
from jimmy.state.session import SessionState
from jimmy.tools.registry import ToolRegistry
from jimmy.utils.limits import truncate_output

EventHandler = Callable[
    [AgentEvent],
    None,
]

PermissionHandler = Callable[
    [str, str, dict[str, Any]],
    bool,
]


class AgentToolRunner:
    """
    Runtime for one model-requested tool call.

    Flow:

        hard guard
            ↓
        progress guard
            ↓
        resolve tool
            ↓
        permission
            ↓
        execute
            ↓
        observe
            ↓
        record progress
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

        def emit(
            event: AgentEvent,
        ) -> None:
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
            )
        )

        # =====================================================
        # 1. HARD TOOL POLICY
        # =====================================================

        guard = self.guard.check(
            tool_name=tool_name,
            arguments=arguments,
            state=state,
        )

        if not guard.allowed:
            reason = guard.reason or "Tool action was rejected."

            state.add_message(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": (
                        f"Tool rejected by runtime.\n{reason}\nChoose a valid tool/action."
                    ),
                }
            )

            self.observability.record(
                "tool_guard_rejection",
                {
                    "session_id": session_id,
                    "task_turn": task_turn,
                    "tool": tool_name,
                    "reason": reason,
                },
            )

            # IMPORTANT:
            # This did not execute.
            # We track it as BLOCKED, not as a tool failure.
            progress.record(
                tool_name,
                arguments,
                success=False,
                changed_workspace=False,
                blocked=True,
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=0.0,
                    message="blocked",
                )
            )

            return False

        # =====================================================
        # 2. ANTI-LOOP / PROGRESS
        # =====================================================

        allowed, reason = progress.can_run(
            tool_name,
            arguments,
        )

        if not allowed:
            message = reason or "Jimmy detected no meaningful progress."

            state.add_message(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": (
                        "Action blocked to prevent a loop.\n"
                        f"{message}\n"
                        "Choose a different approach."
                    ),
                }
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
                )
            )

            # Escalate to the main loop rather than quietly
            # burning the remaining task-turn budget.
            raise RuntimeError(
                message,
            )

        # =====================================================
        # 3. RESOLVE TOOL
        # =====================================================

        try:
            tool = self.tools.get(
                tool_name,
            )
        except Exception as exc:
            progress.record(
                tool_name,
                arguments,
                success=False,
                changed_workspace=False,
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=(time.monotonic() - started_at),
                    message="error",
                )
            )

            raise RuntimeError(
                f"Unknown tool '{tool_name}'.",
            ) from exc

        # =====================================================
        # 4. PERMISSION
        # =====================================================

        permission = self.permissions.check(
            tool,
        )

        if permission.action == PermissionAction.DENY:
            elapsed = time.monotonic() - started_at

            message = f"Permission denied for '{tool_name}'.\n{permission.reason}"

            state.add_message(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": message,
                }
            )

            progress.record(
                tool_name,
                arguments,
                success=False,
                changed_workspace=False,
                blocked=True,
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=elapsed,
                    message="denied",
                )
            )

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

                state.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": (
                            "Permission denied by the user. "
                            "Do not retry unless the user "
                            "explicitly asks again."
                        ),
                    }
                )

                progress.record(
                    tool_name,
                    arguments,
                    success=False,
                    changed_workspace=False,
                    blocked=True,
                )

                emit(
                    AgentEvent(
                        kind="tool_end",
                        turn=task_turn,
                        tool_name=tool_name,
                        elapsed=elapsed,
                        message="denied",
                    )
                )

                return False

        # =====================================================
        # 5. EXECUTE
        # =====================================================

        try:
            tool_result = self.executor.execute(
                tool_name=tool_name,
                arguments=arguments,
            )

        except Exception as exc:
            elapsed = time.monotonic() - started_at

            metrics.failures += 1

            state.add_message(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": (f"Tool '{tool_name}' failed.\n{type(exc).__name__}: {exc}"),
                }
            )

            self.observability.record(
                "tool_call",
                {
                    "session_id": session_id,
                    "task_turn": task_turn,
                    "tool": tool_name,
                    "success": False,
                    "elapsed_seconds": elapsed,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

            progress.record(
                tool_name,
                arguments,
                success=False,
                changed_workspace=False,
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=elapsed,
                    message="error",
                )
            )

            recovery = self.recovery.recover(
                RuntimeError(
                    str(exc),
                ),
            )

            if not recovery.should_continue:
                raise RuntimeError(
                    recovery.message,
                ) from exc

            return False

        # =====================================================
        # 6. NORMALIZE OUTPUT
        # =====================================================

        if tool_result.success:
            output = truncate_output(
                tool_result.output or "",
            )
        else:
            output = truncate_output(
                (
                    f"Tool '{tool_name}' failed.\n"
                    f"Error type: {tool_result.error_type}\n"
                    f"Error: {tool_result.error or 'Unknown error'}"
                ),
            )

        elapsed = time.monotonic() - started_at

        metrics.add_tool_time(
            tool_name=tool_name,
            elapsed=elapsed,
        )

        self.observability.record(
            "tool_call",
            {
                "session_id": session_id,
                "task_turn": task_turn,
                "tool": tool_name,
                "success": tool_result.success,
                "elapsed_seconds": elapsed,
                "error_type": tool_result.error_type,
            },
        )

        # =====================================================
        # 7. OBSERVATION
        # =====================================================

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

        state.add_message(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": observation.result,
            }
        )

        emit(
            AgentEvent(
                kind="tool_end",
                turn=task_turn,
                tool_name=tool_name,
                elapsed=elapsed,
                message=("ok" if tool_result.success else "error"),
            )
        )

        # =====================================================
        # 8. FAILURE / RECOVERY
        # =====================================================

        if not tool_result.success:
            metrics.failures += 1

            progress.record(
                tool_name,
                arguments,
                success=False,
                changed_workspace=False,
            )

            recovery = self.recovery.recover(
                RuntimeError(
                    tool_result.error or "Unknown tool error.",
                ),
            )

            if not recovery.should_continue:
                raise RuntimeError(
                    recovery.message,
                )

            return False

        # =====================================================
        # 9. SUCCESS / PROGRESS
        # =====================================================

        changed_workspace = not tool.metadata.read_only

        progress.record(
            tool_name,
            arguments,
            success=True,
            changed_workspace=changed_workspace,
        )

        # =====================================================
        # 10. EXPLICIT COMPLETION
        # =====================================================

        return bool(
            (tool_result.metadata or {}).get(
                "task_complete",
                False,
            )
        )
