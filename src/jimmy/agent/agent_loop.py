import time
from collections.abc import Callable

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
from jimmy.agent.observer import Observer
from jimmy.agent.planner import Planner
from jimmy.agent.recovery import RecoveryManager
from jimmy.llm.base import LLMProvider
from jimmy.state.session import SessionState
from jimmy.tools.registry import ToolRegistry
from jimmy.utils.limits import truncate_output

from .prompt import SYSTEM_PROMPT

EventHandler = Callable[[AgentEvent], None]


class AgentLoop:
    """Coordinates planning, LLM reasoning, tool execution, observation, and recovery."""

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        max_turns: int = 20,
        planner: Planner | None = None,
        executor: ToolExecutor | None = None,
        observer: Observer | None = None,
        recovery: RecoveryManager | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_turns = max_turns

        self.planner = planner or Planner()
        self.executor = executor or ToolExecutor(tools)
        self.observer = observer or Observer()
        self.recovery = recovery or RecoveryManager()

    def run(
        self,
        task: str,
        on_event: EventHandler | None = None,
    ) -> str:
        """Run Jimmy until the task is complete."""

        started_at = time.monotonic()

        def emit(event: AgentEvent) -> None:
            if on_event is not None:
                on_event(event)

        plan_state = self.planner.create_initial_plan(task)

        state = SessionState(
            task=task,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": (f"Task:\n{task}\n\nCurrent plan:\n{plan_state.summary()}"),
                },
            ],
        )

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

            try:
                response = self.llm.chat(
                    messages=state.messages,
                    tools=tool_schemas,
                )
            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
            ) as exc:
                total_elapsed = time.monotonic() - started_at

                message = f"LLM request failed.\nError type: {type(exc).__name__}\nError: {exc}"

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
                        else f"{len(response.tool_calls)} tool call(s)"
                    ),
                )
            )

            if response.assistant_message:
                state.add_message(response.assistant_message)

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
                    raw_result = self.executor.execute(
                        tool_name=tool_call.name,
                        arguments=tool_call.arguments,
                    )

                    result = truncate_output(str(raw_result))

                    tool_elapsed = time.monotonic() - tool_started_at

                    observation = self.observer.observe_success(
                        tool_name=tool_call.name,
                        result=result,
                    )

                    emit(
                        AgentEvent(
                            kind="tool_end",
                            turn=turn,
                            tool_name=tool_call.name,
                            elapsed=tool_elapsed,
                            message="ok",
                        )
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

                    observation = self.observer.observe_failure(
                        tool_name=tool_call.name,
                        error=exc,
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

                    recovery_decision = self.recovery.recover(exc)

                    if not recovery_decision.should_continue:
                        total_elapsed = time.monotonic() - started_at
                        message = recovery_decision.message

                        emit(
                            AgentEvent(
                                kind="error",
                                turn=turn,
                                elapsed=total_elapsed,
                                message=message,
                            )
                        )

                        raise RuntimeError(message) from exc

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
