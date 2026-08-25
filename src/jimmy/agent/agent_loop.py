import time
from collections.abc import Callable
from pathlib import Path

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

        self.git_state = git_state if git_state is not None else GitState(workspace)

        self.permissions = (
            permission_manager if permission_manager is not None else PermissionManager()
        )

        # IMPORTANT:
        # Use the concrete implementation by default.
        #
        # It stores sessions outside the project,
        # so .jimmy does not become a Git change.
        self.session_store = (
            session_store if session_store is not None else JsonSessionStore(Path.home())
        )

        self.context_manager = ContextManager(
            summarizer=ContextSummarizer(llm),
        )

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

        session_id = self.session_store.create(state)

        self.session_store.save(
            session_id=session_id,
            state=state,
            status="running",
        )

        try:
            return self._run_state(
                state=state,
                session_id=session_id,
                started_at=started_at,
                on_event=on_event,
                on_permission=on_permission,
            )

        except KeyboardInterrupt:
            self.session_store.save(
                session_id=session_id,
                state=state,
                status="interrupted",
            )
            raise

        except Exception:
            self.session_store.save(
                session_id=session_id,
                state=state,
                status="failed",
            )
            raise

    def resume(
        self,
        session_id: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
    ) -> str:
        """Resume a saved session."""

        # load() returns SessionState directly.
        state = self.session_store.load(session_id)

        started_at = time.monotonic()

        self.session_store.save(
            session_id=session_id,
            state=state,
            status="running",
        )

        try:
            return self._run_state(
                state=state,
                session_id=session_id,
                started_at=started_at,
                on_event=on_event,
                on_permission=on_permission,
            )

        except KeyboardInterrupt:
            self.session_store.save(
                session_id=session_id,
                state=state,
                status="interrupted",
            )
            raise

        except Exception:
            self.session_store.save(
                session_id=session_id,
                state=state,
                status="failed",
            )
            raise

    def _run_state(
        self,
        state: SessionState,
        session_id: str,
        started_at: float,
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

            # ==============================
            # ASK LLM
            # ==============================

            try:
                context = self.context_manager.prepare(state.messages)

                response = self.llm.chat(
                    messages=context,
                    tools=tool_schemas,
                )

            except LLMProviderError as exc:
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

            # ==============================
            # SAVE ASSISTANT
            # ==============================

            if response.assistant_message:
                state.add_message(response.assistant_message)

                self.session_store.save(
                    session_id=session_id,
                    state=state,
                    status="running",
                )

            # ==============================
            # DONE
            # ==============================

            if not response.tool_calls:
                result = response.content or ""

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

            # ==============================
            # EXECUTE TOOLS
            # ==============================

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

                # ==============================
                # PERMISSION
                # ==============================

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
                                elapsed=(time.monotonic() - tool_started_at),
                                message="denied",
                            )
                        )

                        continue

                elif permission.action == PermissionAction.DENY:
                    message = f"❌ Permission denied for '{tool_call.name}'.\n{permission.reason}"

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

                # ==============================
                # EXECUTE TOOL
                # ==============================

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
                    error_message = str(exc)

                    emit(
                        AgentEvent(
                            kind="tool_end",
                            turn=turn,
                            tool_name=tool_call.name,
                            elapsed=(time.monotonic() - tool_started_at),
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
                            "tool_call_id": (tool_call.id),
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

                # ==============================
                # OBSERVE RESULT
                # ==============================

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

                # ==============================
                # RECOVERY
                # ==============================

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

                # ==============================
                # SAVE TOOL RESULT
                # ==============================

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

        message = f"Jimmy stopped after reaching the maximum of {self.max_turns} turns."

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
