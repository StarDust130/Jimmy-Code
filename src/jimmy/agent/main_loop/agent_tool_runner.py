from __future__ import annotations

import time
from collections.abc import Callable
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

EventHandler = Callable[[AgentEvent], None]

PermissionHandler = Callable[
    [str, str, dict[str, Any]],
    bool,
]


class AgentToolRunner:
    """
    Validate → permission → execute → observe → recover.

    ToolGuard performs deterministic tool-choice validation.
    It never calls the LLM.
    """

    def __init__(
        self,
        tools: ToolRegistry,
        executor: ToolExecutor,
        observer: Observer,
        recovery: RecoveryManager,
        permissions: PermissionManager,
        observability: Observability,
        workspace,
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

        tool_name = str(tool_call.name)

        arguments = dict(tool_call.arguments or {})

        emit(
            AgentEvent(
                kind="tool_start",
                turn=task_turn,
                tool_name=tool_name,
                arguments=arguments,
            )
        )

        # ====================================================
        # 1. TOOL GUARD
        # ====================================================

        guard = self.guard.check(
            tool_name=tool_name,
            arguments=arguments,
            state=state,
        )

        if not guard.allowed:
            reason = guard.reason

            state.add_message(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": (
                        "Tool rejected by Jimmy's tool guard.\n"
                        f"{reason}\n"
                        "Choose a tool that matches the requested action."
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

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=0.0,
                    message="error",
                )
            )

            progress.record(
                tool_name,
                arguments,
                success=False,
                changed_workspace=False,
            )

            # Important:
            #
            # A guard rejection is not a crash.
            #
            # The LLM should see the rejection and choose
            # a better tool on its next decision.
            return False

        # ====================================================
        # 2. PROGRESS / ANTI-LOOP
        # ====================================================

        allowed, reason = progress.can_run(
            tool_name,
            arguments,
        )

        if not allowed:
            state.add_message(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": (f"Tool rejected: {reason}"),
                }
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=0.0,
                    message="error",
                )
            )

            raise RuntimeError(reason)

        # ====================================================
        # 3. RESOLVE TOOL
        # ====================================================

        tool = self.tools.get(tool_name)

        # ====================================================
        # 4. PERMISSION
        # ====================================================

        decision = self.permissions.check(tool)

        if decision.action == PermissionAction.DENY:
            message = f"❌ Permission denied for '{tool_name}'.\n{decision.reason}"

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_name,
                    elapsed=(time.monotonic() - started_at),
                    message="denied",
                )
            )

            raise PermissionError(message)

        if decision.action == PermissionAction.ASK:
            if on_permission is None:
                raise PermissionRequired(
                    tool_name=tool_name,
                    reason=decision.reason,
                    arguments=arguments,
                )

            approved = on_permission(
                tool_name,
                decision.reason,
                arguments,
            )

            if not approved:
                elapsed = time.monotonic() - started_at

                state.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_name,
                        "content": ("Permission denied by the user. Do not retry this action."),
                    }
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

                progress.record(
                    tool_name,
                    arguments,
                    success=False,
                    changed_workspace=False,
                )

                return False

        # ====================================================
        # 5. EXECUTE
        # ====================================================

        try:
            tool_result = self.executor.execute(
                tool_name=tool_name,
                arguments=arguments,
            )

        except Exception as exc:
            elapsed = time.monotonic() - started_at

            metrics.failures += 1

            self.observability.record(
                "tool_call",
                {
                    "session_id": session_id,
                    "task_turn": task_turn,
                    "tool": tool_name,
                    "success": False,
                    "elapsed_seconds": elapsed,
                    "error": str(exc),
                },
            )

            state.add_message(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": (f"Tool failed: {exc}"),
                }
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

            recovery = self.recovery.recover(RuntimeError(str(exc)))

            if not recovery.should_continue:
                raise RuntimeError(recovery.message) from exc

            return False

        # ====================================================
        # 6. NORMALIZE RESULT
        # ====================================================

        output = truncate_output(
            tool_result.output
            if tool_result.success
            else (
                f"Tool '{tool_name}' failed.\n"
                f"Error type: "
                f"{tool_result.error_type}\n"
                f"Error: "
                f"{tool_result.error}"
            )
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
            },
        )

        # ====================================================
        # 7. OBSERVE
        # ====================================================

        if tool_result.success:
            observation = self.observer.observe_success(
                tool_name=tool_name,
                result=output,
            )
        else:
            observation = self.observer.observe_failure(
                tool_name=tool_name,
                error=RuntimeError(tool_result.error or "Unknown tool error."),
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

        # ====================================================
        # 8. TOOL FAILURE / RECOVERY
        # ====================================================

        if not tool_result.success:
            metrics.failures += 1

            progress.record(
                tool_name,
                arguments,
                success=False,
                changed_workspace=False,
            )

            recovery = self.recovery.recover(
                RuntimeError(tool_result.error or "Unknown tool error.")
            )

            if not recovery.should_continue:
                raise RuntimeError(recovery.message)

        # ====================================================
        # 9. SAVE OBSERVATION
        # ====================================================

        state.add_message(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_name,
                "content": observation.result,
            }
        )

        changed_workspace = tool_result.success and not tool.metadata.read_only

        progress.record(
            tool_name,
            arguments,
            success=tool_result.success,
            changed_workspace=changed_workspace,
        )

        # ====================================================
        # 10. GENERIC COMPLETION
        # ====================================================

        return bool(
            tool_result.success
            and (tool_result.metadata or {}).get(
                "task_complete",
                False,
            )
        )
