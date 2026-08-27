import time
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
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


class AgentToolRunner:
    """Execute one model-selected tool."""

    def __init__(
        self,
        tools: ToolRegistry,
        executor: ToolExecutor,
        observer: Observer,
        recovery: RecoveryManager,
        permissions: PermissionManager,
        observability: Observability,
    ) -> None:
        self.tools = tools
        self.executor = executor
        self.observer = observer
        self.recovery = recovery
        self.permissions = permissions
        self.observability = observability

    def run(
        self,
        state: SessionState,
        session_id: str,
        metrics: RunMetrics,
        tool_call: Any,
        task_turn: int,
        on_event=None,
        on_permission=None,
    ) -> bool:
        started_at = time.monotonic()

        def emit(event: AgentEvent) -> None:
            if on_event is not None:
                on_event(event)

        emit(
            AgentEvent(
                kind="tool_start",
                turn=task_turn,
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
            )
        )

        tool = self.tools.get(tool_call.name)

        # ----------------------------------------
        # Permission
        # ----------------------------------------

        decision = self.permissions.check(tool)

        if decision.action == PermissionAction.DENY:
            elapsed = time.monotonic() - started_at

            metrics.failures += 1
            metrics.add_tool_time(
                tool_name=tool_call.name,
                elapsed=elapsed,
            )

            message = f"❌ Permission denied for '{tool_call.name}'.\n{decision.reason}"

            self.observability.record(
                "tool_call",
                {
                    "session_id": session_id,
                    "task_turn": task_turn,
                    "session_turn": state.turn_count,
                    "tool": tool_call.name,
                    "success": False,
                    "elapsed_seconds": elapsed,
                    "error": message,
                },
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_call.name,
                    elapsed=elapsed,
                    message="denied",
                )
            )

            raise PermissionError(message)

        if decision.action == PermissionAction.ASK:
            if on_permission is None:
                raise PermissionRequired(
                    tool_name=tool_call.name,
                    reason=decision.reason,
                    arguments=tool_call.arguments,
                )

            approved = on_permission(
                tool_call.name,
                decision.reason,
                tool_call.arguments,
            )

            if not approved:
                elapsed = time.monotonic() - started_at

                state.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": ("Permission denied by the user."),
                    }
                )

                metrics.add_tool_time(
                    tool_name=tool_call.name,
                    elapsed=elapsed,
                )

                self.observability.record(
                    "tool_call",
                    {
                        "session_id": session_id,
                        "task_turn": task_turn,
                        "session_turn": state.turn_count,
                        "tool": tool_call.name,
                        "success": False,
                        "elapsed_seconds": elapsed,
                        "error": "Permission denied by the user.",
                    },
                )

                emit(
                    AgentEvent(
                        kind="tool_end",
                        turn=task_turn,
                        tool_name=tool_call.name,
                        elapsed=elapsed,
                        message="denied",
                    )
                )

                return False

        # ----------------------------------------
        # Execute
        # ----------------------------------------

        try:
            tool_result = self.executor.execute(
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
            )
        except Exception as exc:
            elapsed = time.monotonic() - started_at

            metrics.failures += 1

            self.observability.record(
                "tool_call",
                {
                    "session_id": session_id,
                    "task_turn": task_turn,
                    "session_turn": state.turn_count,
                    "tool": tool_call.name,
                    "success": False,
                    "elapsed_seconds": elapsed,
                    "error": str(exc),
                },
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=task_turn,
                    tool_name=tool_call.name,
                    elapsed=elapsed,
                    message="error",
                )
            )

            # Let the recovery system decide whether another
            # attempt is meaningful.
            recovery = self.recovery.recover(RuntimeError(str(exc)))

            if not recovery.should_continue:
                raise RuntimeError(recovery.message) from exc

            state.add_message(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "content": f"Tool failed: {exc}",
                }
            )

            # IMPORTANT:
            # The action did not succeed.
            # Never report task completion.
            return False

        # ----------------------------------------
        # Build output
        # ----------------------------------------

        output = truncate_output(
            tool_result.output
            if tool_result.success
            else (
                f"Tool '{tool_call.name}' failed.\n"
                f"Error type: {tool_result.error_type}\n"
                f"Error: {tool_result.error}"
            )
        )

        elapsed = time.monotonic() - started_at

        metrics.add_tool_time(
            tool_name=tool_call.name,
            elapsed=elapsed,
        )

        self.observability.record(
            "tool_call",
            {
                "session_id": session_id,
                "task_turn": task_turn,
                "session_turn": state.turn_count,
                "tool": tool_call.name,
                "success": tool_result.success,
                "elapsed_seconds": elapsed,
            },
        )

        # ----------------------------------------
        # Observe
        # ----------------------------------------

        if tool_result.success:
            observation = self.observer.observe_success(
                tool_name=tool_call.name,
                result=output,
            )
        else:
            observation = self.observer.observe_failure(
                tool_name=tool_call.name,
                error=RuntimeError(tool_result.error or "Unknown tool error."),
            )

        emit(
            AgentEvent(
                kind="tool_end",
                turn=task_turn,
                tool_name=tool_call.name,
                elapsed=elapsed,
                message=("ok" if tool_result.success else "error"),
            )
        )

        # ----------------------------------------
        # Tool failure
        # ----------------------------------------

        if not tool_result.success:
            metrics.failures += 1

            recovery = self.recovery.recover(
                RuntimeError(tool_result.error or "Unknown tool error.")
            )

            if not recovery.should_continue:
                raise RuntimeError(recovery.message)

        # ----------------------------------------
        # Save result
        # ----------------------------------------

        state.add_message(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "content": observation.result,
            }
        )

        # ----------------------------------------
        # Completion
        # ----------------------------------------

        return bool(
            tool_result.success
            and (tool_result.metadata or {}).get(
                "task_complete",
                False,
            )
        )
