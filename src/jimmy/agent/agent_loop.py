import time
from collections.abc import Callable

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
from jimmy.state.session import SessionState
from jimmy.tools.registry import ToolRegistry
from jimmy.utils.limits import truncate_output

from .prompt import SYSTEM_PROMPT

EventHandler = Callable[[AgentEvent], None]


class AgentLoop:
    """Generic ReAct loop for all Jimmy tasks."""

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        workspace,
        max_turns: int = 20,
        planner: Planner | None = None,
        executor: ToolExecutor | None = None,
        observer: Observer | None = None,
        recovery: RecoveryManager | None = None,
        explorer: CodebaseExplorer | None = None,
        git_state: GitState | None = None,
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
        self.git_state = git_state or GitState(workspace)

        self.context_manager = ContextManager(
            summarizer=ContextSummarizer(llm),
        )

    def run(
        self,
        task: str,
        on_event: EventHandler | None = None,
    ) -> str:
        """Run Jimmy until the model decides the task is complete."""

        started_at = time.monotonic()

        def emit(event: AgentEvent) -> None:
            if on_event is not None:
                on_event(event)

        # Keep planning cheap for small tasks.
        plan_state = None

        if len(task.split()) >= 15:
            plan_state = self.planner.create_initial_plan(task)

        # Explore once at session start.
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

        # Every task gets the same tool set.
        tool_schemas = self.tools.schemas()

        while state.turn_count < self.max_turns:
            turn = state.next_turn()
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
                context = self.context_manager.prepare(
                    state.messages,
                )

                response = self.llm.chat(
                    messages=context,
                    tools=tool_schemas,
                )

            except LLMProviderError as exc:
                total_elapsed = time.monotonic() - started_at

                message = str(exc)

                emit(
                    AgentEvent(
                        kind="error",
                        turn=turn,
                        elapsed=total_elapsed,
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
                total_elapsed = time.monotonic() - started_at

                message = f"❌ LLM request failed.\n{exc}"

                emit(
                    AgentEvent(
                        kind="error",
                        turn=turn,
                        elapsed=total_elapsed,
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

            # Save model response.
            if response.assistant_message:
                state.add_message(response.assistant_message)

            # ==============================
            # DONE
            # ==============================

            if not response.tool_calls:
                total_elapsed = time.monotonic() - started_at

                result = response.content or ""

                emit(
                    AgentEvent(
                        kind="complete",
                        turn=turn,
                        elapsed=total_elapsed,
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
                    PermissionError,
                    FileNotFoundError,
                ) as exc:
                    tool_elapsed = time.monotonic() - tool_started_at

                    message = str(exc)

                    emit(
                        AgentEvent(
                            kind="tool_end",
                            turn=turn,
                            tool_name=tool_call.name,
                            elapsed=tool_elapsed,
                            message="error",
                        )
                    )

                    recovery_exception = RuntimeError(message)

                    recovery_decision = self.recovery.recover(recovery_exception)

                    if not recovery_decision.should_continue:
                        total_elapsed = time.monotonic() - started_at

                        error_message = recovery_decision.message

                        emit(
                            AgentEvent(
                                kind="error",
                                turn=turn,
                                elapsed=total_elapsed,
                                message=error_message,
                            )
                        )

                        raise RuntimeError(error_message) from recovery_exception

                    state.add_message(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": (f"Tool failed: {message}"),
                        }
                    )

                    continue

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

                # Recover failed tools.
                if not tool_result.success:
                    recovery_exception = RuntimeError(tool_result.error or "Unknown tool error.")

                    recovery_decision = self.recovery.recover(recovery_exception)

                    if not recovery_decision.should_continue:
                        total_elapsed = time.monotonic() - started_at

                        error_message = recovery_decision.message

                        emit(
                            AgentEvent(
                                kind="error",
                                turn=turn,
                                elapsed=total_elapsed,
                                message=error_message,
                            )
                        )

                        raise RuntimeError(error_message) from recovery_exception

                # Send result back to the LLM.
                state.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": observation.result,
                    }
                )

        total_elapsed = time.monotonic() - started_at

        message = f"Jimmy stopped after reaching the maximum of {self.max_turns} turns."

        emit(
            AgentEvent(
                kind="error",
                turn=state.turn_count,
                elapsed=total_elapsed,
                message=message,
            )
        )

        raise RuntimeError(message)
