import time
from collections.abc import Callable

from jimmy.agent.events import AgentEvent
from jimmy.llm.base import LLMProvider
from jimmy.state.session import SessionState
from jimmy.tools.registry import ToolRegistry
from jimmy.utils.limits import truncate_output

SYSTEM_PROMPT = """You are Jimmy, a terminal-native coding agent.

You work inside the user's current project.

Use the available tools to inspect files, search code, edit files,
and run commands when needed.

Do not claim you changed something unless you actually used a tool
to make the change.

Keep working until the task is complete.
"""


EventHandler = Callable[[AgentEvent], None]


class AgentLoop:
    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        max_turns: int = 20,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_turns = max_turns

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

        state = SessionState(
            task=task,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": task,
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

            response = self.llm.chat(
                messages=state.messages,
                tools=tool_schemas,
            )

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
                    tool = self.tools.get(tool_call.name)

                    raw_result = tool.execute(tool_call.arguments)

                    result = truncate_output(str(raw_result))

                    tool_elapsed = time.monotonic() - tool_started_at

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
                ) as exc:
                    result = (
                        f"Tool '{tool_call.name}' failed.\n"
                        f"Error type: {type(exc).__name__}\n"
                        f"Error: {exc}"
                    )

                    tool_elapsed = time.monotonic() - tool_started_at

                    emit(
                        AgentEvent(
                            kind="tool_end",
                            turn=turn,
                            tool_name=tool_call.name,
                            elapsed=tool_elapsed,
                            message="error",
                        )
                    )

                state.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": result,
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
