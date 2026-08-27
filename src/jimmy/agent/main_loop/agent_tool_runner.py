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
    Executes one model-selected tool.

    Responsibilities:

    permission → execute → observe → save result
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
        """Execute one tool call and return task_complete."""

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
        # Find tool
        # --------------------------------------------

        tool = self.tools.get(tool_call.name)

        # --------------------------------------------
        # Permission
        # --------------------------------------------

        permission = self.permissions.check(tool)

        if permission.action == PermissionAction.DENY:
            elapsed = time.monotonic() - started_at

            metrics.failures += 1

            metrics.add_tool_time(
                tool_name=tool_call.name,
                elapsed=elapsed,
            )

            message = f"❌ Permission denied for '{tool_call.name}'.\n{permission.reason}"

            self.observability.record(
                "tool_call",
                {
                    "session_id": session_id,
                    "turn": turn,
                    "tool": tool_call.name,
                    "success": False,
                    "elapsed_seconds": elapsed,
                    "reason": "permission_denied",
                },
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

            raise PermissionError(message)

        if permission.action == PermissionAction.ASK:
            if on_permission is None:
                raise PermissionRequired(
                    tool_name=tool_call.name,
                    reason=permission.reason,
                    arguments=tool_call.arguments,
                )

            approved = on_permission(
                tool_call.name,
                permission.reason,
                tool_call.arguments,
            )

            if not approved:
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
                        "success": False,
                        "elapsed_seconds": elapsed,
                        "reason": "permission_denied",
                    },
                )

                state.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": ("Permission denied by the user. Do not retry this action."),
                    }
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
            tool_result = self.executor.execute(
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

        result = truncate_output(
            tool_result.output
            if tool_result.success
            else (
                f"Tool '{tool_call.name}' failed.\n"
                f"Error type: "
                f"{tool_result.error_type}\n"
                f"Error: "
                f"{tool_result.error}"
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
                "success": tool_result.success,
                "elapsed_seconds": elapsed,
            },
        )

        # --------------------------------------------
        # Observe
        # --------------------------------------------

        if tool_result.success:
            observation = self.observer.observe_success(
                tool_name=tool_call.name,
                result=result,
            )
        else:
            observation = self.observer.observe_failure(
                tool_name=tool_call.name,
                error=RuntimeError(tool_result.error or "Unknown tool error."),
            )

        emit(
            AgentEvent(
                kind="tool_end",
                turn=turn,
                tool_name=tool_call.name,
                elapsed=elapsed,
                message=("ok" if tool_result.success else "error"),
            )
        )

        # --------------------------------------------
        # Failed tool
        # --------------------------------------------

        if not tool_result.success:
            metrics.failures += 1

            recovery = self.recovery.recover(
                RuntimeError(tool_result.error or "Unknown tool error.")
            )

            if not recovery.should_continue:
                raise RuntimeError(recovery.message)

        # --------------------------------------------
        # Save result for next LLM decision
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
        # Generic completion flag
        # --------------------------------------------

        return bool(
            tool_result.success
            and (tool_result.metadata or {}).get(
                "task_complete",
                False,
            )
        )
