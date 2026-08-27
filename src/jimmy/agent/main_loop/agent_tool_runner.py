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
    """
    Execute one model-selected tool.

    This class does not choose tools.
    It only validates permission, executes, observes,
    and returns whether the tool completed the task.
    """

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
        on_event=None,
        on_permission=None,
    ) -> bool:
        started_at = time.monotonic()
        turn = state.turn_count

        def emit(event: AgentEvent) -> None:
            if on_event is not None:
                on_event(event)

        emit(
            AgentEvent(
                kind="tool_start",
                turn=turn,
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
            )
        )

        # --------------------------------------------
        # Resolve tool
        # --------------------------------------------

        tool = self.tools.get(tool_call.name)

        # --------------------------------------------
        # Permission
        # --------------------------------------------

        decision = self.permissions.check(tool)

        if decision.action == PermissionAction.DENY:
            raise PermissionError(
                f"❌ Permission denied for '{tool_call.name}'.\n{decision.reason}"
            )

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
                        "content": ("Permission denied by the user. Do not retry this action."),
                    }
                )

                metrics.add_tool_time(
                    tool_name=tool_call.name,
                    elapsed=elapsed,
                )

                emit(
                    AgentEvent(
                        kind="tool_end",
                        turn=turn,
                        tool_name=tool_call.name,
                        elapsed=elapsed,
                        message="denied",
                    )
                )

                return False

        # --------------------------------------------
        # Execute
        # --------------------------------------------

        try:
            result = self.executor.execute(
                tool_name=tool_call.name,
                arguments=tool_call.arguments,
            )

        except Exception as exc:
            elapsed = time.monotonic() - started_at

            metrics.failures += 1

            metrics.add_tool_time(
                tool_name=tool_call.name,
                elapsed=elapsed,
            )

            self.observability.record(
                "tool_call",
                {
                    "session_id": session_id,
                    "turn": turn,
                    "tool": tool_call.name,
                    "success": False,
                    "elapsed_seconds": elapsed,
                    "error": str(exc),
                },
            )

            emit(
                AgentEvent(
                    kind="tool_end",
                    turn=turn,
                    tool_name=tool_call.name,
                    elapsed=elapsed,
                    message="error",
                )
            )

            recovery = self.recovery.recover(RuntimeError(str(exc)))

            if not recovery.should_continue:
                raise RuntimeError(recovery.message) from exc

            state.add_message(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "content": (f"Tool failed: {exc}"),
                }
            )

            return False

        # --------------------------------------------
        # Normalize result
        # --------------------------------------------

        output = truncate_output(
            result.output
            if result.success
            else (
                f"Tool '{tool_call.name}' failed.\n"
                f"Error type: {result.error_type}\n"
                f"Error: {result.error}"
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
                "turn": turn,
                "tool": tool_call.name,
                "success": result.success,
                "elapsed_seconds": elapsed,
            },
        )

        # --------------------------------------------
        # Observation
        # --------------------------------------------

        if result.success:
            observation = self.observer.observe_success(
                tool_name=tool_call.name,
                result=output,
            )
        else:
            observation = self.observer.observe_failure(
                tool_name=tool_call.name,
                error=RuntimeError(result.error or "Unknown tool error."),
            )

        emit(
            AgentEvent(
                kind="tool_end",
                turn=turn,
                tool_name=tool_call.name,
                elapsed=elapsed,
                message=("ok" if result.success else "error"),
            )
        )

        # --------------------------------------------
        # Tool failure
        # --------------------------------------------

        if not result.success:
            metrics.failures += 1

            recovery = self.recovery.recover(RuntimeError(result.error or "Unknown tool error."))

            if not recovery.should_continue:
                raise RuntimeError(recovery.message)

        # --------------------------------------------
        # Save result
        # --------------------------------------------

        state.add_message(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.name,
                "content": observation.result,
            }
        )

        # --------------------------------------------
        # Generic completion
        # --------------------------------------------

        return bool(
            result.success
            and (result.metadata or {}).get(
                "task_complete",
                False,
            )
        )
