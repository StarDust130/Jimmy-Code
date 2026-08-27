import time
from collections.abc import Callable
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
from jimmy.agent.observer import Observer
from jimmy.agent.recovery import RecoveryManager
from jimmy.context.context import ContextManager
from jimmy.llm.base import LLMProvider
from jimmy.llm.errors import LLMProviderError
from jimmy.observability.metrics import (
    LLMUsage,
    Observability,
    RunMetrics,
)
from jimmy.permissions.errors import PermissionRequired
from jimmy.permissions.manager import (
    PermissionAction,
    PermissionManager,
)
from jimmy.session.store import SessionStore
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


class MainLoop:
    """
    Jimmy's core execution engine.

    The loop is intentionally small:

        ask → act → observe → continue/done

    Other systems are supporting capabilities, not
    mandatory steps for every task.
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
        self.llm = llm
        self.tools = tools
        self.executor = executor
        self.observer = observer
        self.recovery = recovery
        self.context_manager = context_manager
        self.permissions = permissions
        self.session_store = session_store
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
        def emit(
            event: AgentEvent,
        ) -> None:
            if on_event is not None:
                on_event(event)

        # The LLM gets all available tools.
        # It decides which tool is useful for the task.
        tool_schemas = self.tools.schemas()

        while state.turn_count < max_turns:
            turn = state.next_turn()

            self.session_store.save(
                session_id=session_id,
                state=state,
                status="running",
            )

            turn_started_at = time.monotonic()

            emit(
                AgentEvent(
                    kind="turn_start",
                    turn=turn,
                )
            )

            # ==========================================
            # 1. ASK THE LLM
            # ==========================================

            try:
                context = self.context_manager.prepare(state.messages)

                response = self.llm.chat(
                    messages=context,
                    tools=tool_schemas,
                )

                # ------------------------------
                # Observability
                # ------------------------------

                usage = LLMUsage.from_dict(
                    getattr(
                        response,
                        "usage",
                        None,
                    )
                )

                model_name = getattr(
                    self.llm,
                    "model",
                    type(self.llm).__name__,
                )

                llm_elapsed = time.monotonic() - turn_started_at

                metrics.turns = state.turn_count

                metrics.add_llm_usage(
                    model=model_name,
                    usage=usage,
                )

                self.observability.record(
                    "llm_call",
                    {
                        "session_id": session_id,
                        "turn": turn,
                        "model": model_name,
                        "input_tokens": (usage.input_tokens),
                        "output_tokens": (usage.output_tokens),
                        "total_tokens": (usage.total_tokens),
                        "cost_usd": (usage.cost_usd),
                        "elapsed_seconds": (llm_elapsed),
                    },
                )

            except LLMProviderError as exc:
                raise RuntimeError(str(exc)) from exc

            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
            ) as exc:
                raise RuntimeError(f"❌ LLM request failed.\n{type(exc).__name__}: {exc}") from exc

            # ==========================================
            # 2. SAVE ASSISTANT MESSAGE
            # ==========================================

            if response.assistant_message:
                state.add_message(response.assistant_message)

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

            # ==========================================
            # 3. NO TOOL CALL = DONE
            # ==========================================

            if not response.tool_calls:
                result = response.content or ""

                metrics.finish(time.monotonic() - started_at)

                self.observability.record_run(
                    metrics,
                    status="completed",
                )

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="completed",
                )

                emit(
                    AgentEvent(
                        kind="turn_end",
                        turn=turn,
                        elapsed=(time.monotonic() - turn_started_at),
                        message="final response",
                    )
                )

                emit(
                    AgentEvent(
                        kind="complete",
                        turn=turn,
                        elapsed=(time.monotonic() - started_at),
                        message=result,
                    )
                )

                return result

            # ==========================================
            # 4. EXECUTE TOOLS
            # ==========================================

            for tool_call in response.tool_calls:
                tool_started_at = time.monotonic()

                emit(
                    AgentEvent(
                        kind="tool_start",
                        turn=turn,
                        tool_name=tool_call.name,
                        arguments=tool_call.arguments,
                    )
                )

                # --------------------------------------
                # Permission
                # --------------------------------------

                tool = self.tools.get(tool_call.name)

                permission = self.permissions.check(tool)

                if permission.action == PermissionAction.DENY:
                    message = f"❌ Permission denied for '{tool_call.name}'.\n{permission.reason}"

                    metrics.failures += 1

                    emit(
                        AgentEvent(
                            kind="tool_end",
                            turn=turn,
                            tool_name=tool_call.name,
                            elapsed=(time.monotonic() - tool_started_at),
                            message="denied",
                        )
                    )

                    raise PermissionError(message)

                if permission.action == PermissionAction.ASK:
                    if on_permission is None:
                        raise PermissionRequired(
                            tool_name=tool_call.name,
                            reason=permission.reason,
                            arguments=(tool_call.arguments),
                        )

                    approved = on_permission(
                        tool_call.name,
                        permission.reason,
                        tool_call.arguments,
                    )

                    if not approved:
                        state.add_message(
                            {
                                "role": "tool",
                                "tool_call_id": (tool_call.id),
                                "name": (tool_call.name),
                                "content": (
                                    "Permission denied by the user. Do not retry this tool call."
                                ),
                            }
                        )

                        tool_elapsed = time.monotonic() - tool_started_at

                        metrics.add_tool_time(
                            tool_name=tool_call.name,
                            elapsed=tool_elapsed,
                        )

                        self.observability.record(
                            "tool_call",
                            {
                                "session_id": (session_id),
                                "turn": turn,
                                "tool": (tool_call.name),
                                "success": False,
                                "elapsed_seconds": (tool_elapsed),
                            },
                        )

                        self.session_store.save(
                            session_id=session_id,
                            state=state,
                            status="running",
                        )

                        emit(
                            AgentEvent(
                                kind="tool_end",
                                turn=turn,
                                tool_name=(tool_call.name),
                                elapsed=tool_elapsed,
                                message="denied",
                            )
                        )

                        continue

                # --------------------------------------
                # Execute
                # --------------------------------------

                try:
                    tool_result = self.executor.execute(
                        tool_name=tool_call.name,
                        arguments=tool_call.arguments,
                    )

                except (
                    ValueError,
                    TypeError,
                    OSError,
                    RuntimeError,
                    TimeoutError,
                    FileNotFoundError,
                ) as exc:
                    tool_elapsed = time.monotonic() - tool_started_at

                    metrics.failures += 1

                    metrics.add_tool_time(
                        tool_name=tool_call.name,
                        elapsed=tool_elapsed,
                    )

                    self.observability.record(
                        "tool_call",
                        {
                            "session_id": (session_id),
                            "turn": turn,
                            "tool": (tool_call.name),
                            "success": False,
                            "elapsed_seconds": (tool_elapsed),
                        },
                    )

                    emit(
                        AgentEvent(
                            kind="tool_end",
                            turn=turn,
                            tool_name=tool_call.name,
                            elapsed=tool_elapsed,
                            message="error",
                        )
                    )

                    recovery_decision = self.recovery.recover(RuntimeError(str(exc)))

                    if not recovery_decision.should_continue:
                        raise RuntimeError(recovery_decision.message) from exc

                    state.add_message(
                        {
                            "role": "tool",
                            "tool_call_id": (tool_call.id),
                            "name": (tool_call.name),
                            "content": (f"Tool failed: {exc}"),
                        }
                    )

                    self.session_store.save(
                        session_id=session_id,
                        state=state,
                        status="running",
                    )

                    continue

                # --------------------------------------
                # Observe
                # --------------------------------------

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

                tool_elapsed = time.monotonic() - tool_started_at

                metrics.add_tool_time(
                    tool_name=tool_call.name,
                    elapsed=tool_elapsed,
                )

                self.observability.record(
                    "tool_call",
                    {
                        "session_id": session_id,
                        "turn": turn,
                        "tool": tool_call.name,
                        "success": (tool_result.success),
                        "elapsed_seconds": (tool_elapsed),
                    },
                )

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
                        elapsed=tool_elapsed,
                        message=("ok" if tool_result.success else "error"),
                    )
                )

                # --------------------------------------
                # Tool failure
                # --------------------------------------

                if not tool_result.success:
                    metrics.failures += 1

                    recovery_decision = self.recovery.recover(
                        RuntimeError(tool_result.error or "Unknown tool error.")
                    )

                    if not recovery_decision.should_continue:
                        raise RuntimeError(recovery_decision.message)

                # --------------------------------------
                # Save observation
                # --------------------------------------

                state.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": (tool_call.id),
                        "name": tool_call.name,
                        "content": observation.result,
                    }
                )

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

                # --------------------------------------
                # Generic tool completion
                # --------------------------------------

                if tool_result.success and tool_result.metadata.get("task_complete") is True:
                    result = tool_result.output or "Task completed."

                    metrics.finish(time.monotonic() - started_at)

                    self.observability.record_run(
                        metrics,
                        status="completed",
                    )

                    self.session_store.save(
                        session_id=session_id,
                        state=state,
                        status="completed",
                    )

                    emit(
                        AgentEvent(
                            kind="complete",
                            turn=turn,
                            elapsed=(time.monotonic() - started_at),
                            message=result,
                        )
                    )

                    return result

        # ==========================================
        # MAX TURNS
        # ==========================================

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

        metrics.finish(time.monotonic() - started_at)

        self.observability.record_run(
            metrics,
            status="failed",
        )

        self.session_store.save(
            session_id=session_id,
            state=state,
            status="failed",
        )

        emit(
            AgentEvent(
                kind="error",
                turn=state.turn_count,
                elapsed=(time.monotonic() - started_at),
                message=message,
            )
        )

        raise RuntimeError(message)
