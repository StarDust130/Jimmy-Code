import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
from jimmy.agent.observer import Observer
from jimmy.agent.planner import Planner
from jimmy.agent.recovery import RecoveryManager
from jimmy.context.context import ContextManager
from jimmy.context.context_summarizer import ContextSummarizer
from jimmy.exploration.explorer import CodebaseExplorer
from jimmy.git.state import GitState
from jimmy.llm.base import LLMProvider
from jimmy.llm.errors import LLMProviderError
from jimmy.observability.metrics import (
    LLMUsage,
    Observability,
)
from jimmy.permissions.errors import PermissionRequired
from jimmy.permissions.manager import (
    PermissionAction,
    PermissionManager,
)
from jimmy.session.json_store import JsonSessionStore
from jimmy.session.store import SessionStore
from jimmy.state.session import SessionState
from jimmy.tools.registry import ToolRegistry
from jimmy.utils.limits import truncate_output

from .prompt import SYSTEM_PROMPT

PermissionHandler = Callable[
    [str, str, dict],
    bool,
]

EventHandler = Callable[[AgentEvent], None]


class AgentLoop:
    """Generic ReAct loop for all Jimmy tasks."""

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        workspace: Path,
        max_turns: int = 20,
        planner: Planner | None = None,
        executor: ToolExecutor | None = None,
        observer: Observer | None = None,
        recovery: RecoveryManager | None = None,
        explorer: CodebaseExplorer | None = None,
        git_state: GitState | None = None,
        permission_manager: PermissionManager | None = None,
        session_store: SessionStore | None = None,
        observability: Observability | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.workspace = workspace
        self.max_turns = max_turns

        self.planner = planner or Planner(llm)
        self.executor = executor or ToolExecutor(tools)
        self.observer = observer or Observer()
        self.recovery = recovery or RecoveryManager()
        self.explorer = explorer or CodebaseExplorer(workspace)
        self.observability = observability or Observability()

        self.git_state = git_state if git_state is not None else GitState(workspace)

        self.permissions = (
            permission_manager if permission_manager is not None else PermissionManager()
        )

        # 💾 Keep session data outside the project.
        # This prevents .jimmy files from showing up in Git.
        self.session_store = (
            session_store if session_store is not None else JsonSessionStore(Path.home())
        )

        self.context_manager = ContextManager(
            summarizer=ContextSummarizer(llm),
        )

    # ============================================================
    # 🚀 1️⃣ START NEW SESSION
    # ============================================================

    def run(
        self,
        task: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
    ) -> str:
        """Start a new Jimmy session."""

        started_at = time.monotonic()

        plan_state = None

        if len(task.split()) >= 15:
            plan_state = self.planner.create_initial_plan(task)

        exploration_summary = self.explorer.summary()

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": task,
            },
            {
                "role": "system",
                "content": (f"Initial workspace exploration:\n{exploration_summary}"),
            },
        ]

        if plan_state is not None:
            messages.append(
                {
                    "role": "system",
                    "content": (f"Current execution plan:\n{plan_state.summary()}"),
                }
            )

        state = SessionState(
            task=task,
            messages=messages,
        )

        # Create the session BEFORE starting observability
        # because observability needs the session ID.
        session_id = self.session_store.create(state)

        self.session_store.save(
            session_id=session_id,
            state=state,
            status="running",
        )

        metrics = self.observability.start_run(
            task=task,
            session_id=session_id,
        )

        try:
            return self._run_state(
                state=state,
                session_id=session_id,
                started_at=started_at,
                metrics=metrics,
                on_event=on_event,
                on_permission=on_permission,
            )

        except KeyboardInterrupt:
            metrics.finish(time.monotonic() - started_at)

            self.observability.record_run(
                metrics,
                status="interrupted",
            )

            self.session_store.save(
                session_id=session_id,
                state=state,
                status="interrupted",
            )

            raise

        except Exception as exc:
            metrics.failures += 1

            self.observability.record(
                "error",
                {
                    "session_id": session_id,
                    "turn": state.turn_count,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
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

            raise

    # ============================================================
    # 🔄 2️⃣ RESUME SESSION
    # ============================================================

    def resume(
        self,
        session_id: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
    ) -> str:
        """Resume a saved session."""

        state = self.session_store.load(session_id)

        started_at = time.monotonic()

        self.session_store.save(
            session_id=session_id,
            state=state,
            status="running",
        )

        metrics = self.observability.start_run(
            task=state.task,
            session_id=session_id,
        )

        try:
            return self._run_state(
                state=state,
                session_id=session_id,
                started_at=started_at,
                metrics=metrics,
                on_event=on_event,
                on_permission=on_permission,
            )

        except KeyboardInterrupt:
            metrics.finish(time.monotonic() - started_at)

            self.observability.record_run(
                metrics,
                status="interrupted",
            )

            self.session_store.save(
                session_id=session_id,
                state=state,
                status="interrupted",
            )

            raise

        except Exception as exc:
            metrics.failures += 1

            self.observability.record(
                "error",
                {
                    "session_id": session_id,
                    "turn": state.turn_count,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
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

            raise

    # ============================================================
    # ! 🟢 3️⃣ MAIN REACT LOOP — START HERE
    # ============================================================

    def _run_state(
        self,
        state: SessionState,
        session_id: str,
        started_at: float,
        metrics: Any,
        on_event: EventHandler | None,
        on_permission: PermissionHandler | None,
    ) -> str:
        """Run the ReAct loop for a new or resumed session."""

        def emit(
            event: AgentEvent,
        ) -> None:
            if on_event is not None:
                on_event(event)

        tool_schemas = self.tools.schemas()

        while state.turn_count < self.max_turns:
            # 🔁 Each turn: ask → act → observe → save → repeat.
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

            # 🤖 1️⃣ Ask the LLM what to do next.

            try:
                context = self.context_manager.prepare(state.messages)

                response = self.llm.chat(
                    messages=context,
                    tools=tool_schemas,
                )

                # 📊 Track LLM usage and timing.

                usage = LLMUsage.from_dict(response.usage)

                metrics.turns = state.turn_count

                model_name = getattr(
                    self.llm,
                    "model",
                    type(self.llm).__name__,
                )

                self.observability.record(
                    "llm_call",
                    {
                        "session_id": session_id,
                        "turn": state.turn_count,
                        "model": model_name,
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "total_tokens": usage.total_tokens,
                        "cost_usd": usage.cost_usd,
                        "elapsed_seconds": (time.monotonic() - turn_started_at),
                    },
                )

                metrics.add_llm_usage(
                    model=model_name,
                    usage=usage,
                )

            except LLMProviderError as exc:
                metrics.failures += 1

                self.observability.record(
                    "error",
                    {
                        "session_id": session_id,
                        "turn": turn,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )

                message = str(exc)

                emit(
                    AgentEvent(
                        kind="error",
                        turn=turn,
                        elapsed=(time.monotonic() - started_at),
                        message=message,
                    )
                )

                raise RuntimeError(message) from exc

            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
            ) as exc:
                metrics.failures += 1

                self.observability.record(
                    "error",
                    {
                        "session_id": session_id,
                        "turn": turn,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )

                message = f"❌ LLM request failed.\n{type(exc).__name__}: {exc}"

                emit(
                    AgentEvent(
                        kind="error",
                        turn=turn,
                        elapsed=(time.monotonic() - started_at),
                        message=message,
                    )
                )

                raise RuntimeError(message) from exc

            turn_elapsed = time.monotonic() - turn_started_at

            emit(
                AgentEvent(
                    kind="turn_end",
                    turn=turn,
                    elapsed=turn_elapsed,
                    message=(
                        "final response"
                        if not response.tool_calls
                        else (f"{len(response.tool_calls)} tool call(s)")
                    ),
                )
            )

            # 💬 2️⃣ Save the assistant response.

            if response.assistant_message:
                state.add_message(response.assistant_message)

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

            # ✅ 3️⃣ No tools needed → task is complete.

            if not response.tool_calls:
                result = response.content or ""

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="completed",
                )

                # 📊 Record the completed run.

                metrics.finish(time.monotonic() - started_at)

                self.observability.record_run(
                    metrics,
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

            # 🛠️ 4️⃣ Execute each tool requested by the LLM.

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

                # 🔐 Check tool permission before execution.

                tool = self.tools.get(tool_call.name)

                permission = self.permissions.check(tool)

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
                                "success": False,
                                "elapsed_seconds": tool_elapsed,
                            },
                        )

                        state.add_message(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_call.name,
                                "content": (
                                    "Permission denied by the user. Do not retry this tool call."
                                ),
                            }
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
                                tool_name=tool_call.name,
                                elapsed=tool_elapsed,
                                message="denied",
                            )
                        )

                        continue

                elif permission.action == PermissionAction.DENY:
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
                            "success": False,
                            "elapsed_seconds": tool_elapsed,
                        },
                    )

                    message = f"❌ Permission denied for '{tool_call.name}'.\n{permission.reason}"

                    emit(
                        AgentEvent(
                            kind="tool_end",
                            turn=turn,
                            tool_name=tool_call.name,
                            elapsed=tool_elapsed,
                            message="denied",
                        )
                    )

                    raise PermissionError(message)

                # ⚙️ Run the tool.

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

                    metrics.add_tool_time(
                        tool_name=tool_call.name,
                        elapsed=tool_elapsed,
                    )

                    metrics.failures += 1

                    self.observability.record(
                        "tool_call",
                        {
                            "session_id": session_id,
                            "turn": turn,
                            "tool": tool_call.name,
                            "success": False,
                            "elapsed_seconds": tool_elapsed,
                        },
                    )

                    self.observability.record(
                        "error",
                        {
                            "session_id": session_id,
                            "turn": turn,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        },
                    )

                    error_message = str(exc)

                    emit(
                        AgentEvent(
                            kind="tool_end",
                            turn=turn,
                            tool_name=tool_call.name,
                            elapsed=tool_elapsed,
                            message="error",
                        )
                    )

                    recovery_exception = RuntimeError(error_message)

                    recovery_decision = self.recovery.recover(recovery_exception)

                    if not recovery_decision.should_continue:
                        final_error = recovery_decision.message

                        emit(
                            AgentEvent(
                                kind="error",
                                turn=turn,
                                elapsed=(time.monotonic() - started_at),
                                message=final_error,
                            )
                        )

                        raise RuntimeError(final_error) from recovery_exception

                    state.add_message(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": (f"Tool failed: {error_message}"),
                        }
                    )

                    self.session_store.save(
                        session_id=session_id,
                        state=state,
                        status="running",
                    )

                    continue

                # 👀 5️⃣ Observe and normalize the tool result.

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

                # 📊 Record tool timing and status.

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
                        "success": tool_result.success,
                        "elapsed_seconds": tool_elapsed,
                    },
                )

                if not tool_result.success:
                    metrics.failures += 1

                    self.observability.record(
                        "error",
                        {
                            "session_id": session_id,
                            "turn": turn,
                            "error": (tool_result.error or "Unknown tool error."),
                            "error_type": (tool_result.error_type or "ToolError"),
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

                # 🩹 Recover when the tool reports an error.

                if not tool_result.success:
                    recovery_exception = RuntimeError(tool_result.error or "Unknown tool error.")

                    recovery_decision = self.recovery.recover(recovery_exception)

                    if not recovery_decision.should_continue:
                        final_error = recovery_decision.message

                        emit(
                            AgentEvent(
                                kind="error",
                                turn=turn,
                                elapsed=(time.monotonic() - started_at),
                                message=final_error,
                            )
                        )

                        raise RuntimeError(final_error) from recovery_exception

                # 💾 6️⃣ Save the observation for the next LLM turn.

                state.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": observation.result,
                    }
                )

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

        # ========================================================
        # 🛑 MAX TURNS REACHED
        # ========================================================

        message = f"Jimmy stopped after reaching the maximum of {self.max_turns} turns."

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
