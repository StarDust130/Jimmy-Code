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
from jimmy.llm.base import LLMProvider
from jimmy.state.session import SessionState
from jimmy.tools.registry import ToolRegistry
from jimmy.utils.limits import truncate_output

from .prompt import SYSTEM_PROMPT

EventHandler = Callable[[AgentEvent], None]


class AgentLoop:
    """Coordinates planning, exploration, reasoning, tools, observation, and recovery."""

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
        self.context_manager = ContextManager(
            summarizer=ContextSummarizer(llm),
        )

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

        # 1️⃣ 📋 Create a plan.
        plan_state = self.planner.create_initial_plan(task)

        # 2️⃣ 🧭 Explore the workspace.
        exploration_summary = self.explorer.summary()

        # 3️⃣ 💬 Build the initial LLM context.
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

        # 4️⃣ 📋 Add the plan to the context.
        if plan_state is not None:
            messages.append(
                {
                    "role": "system",
                    "content": (f"Current execution plan:\n{plan_state.summary()}"),
                }
            )

        # 5️⃣ 🧠 Create session state.
        state = SessionState(
            task=task,
            messages=messages,
        )

        # 🔧 Get tool schemas once.
        tool_schemas = self.tools.schemas()

        # ! 🔄 6️⃣ Start the main agent loop.
        while state.turn_count < self.max_turns:
            turn = state.next_turn()
            turn_started_at = time.monotonic()

            emit(
                AgentEvent(
                    kind="turn_start",
                    turn=turn,
                )
            )

            # 7️⃣ 🤖 Ask the LLM what to do.
            try:
                context = self.context_manager.prepare(
                    state.messages,
                )

                response = self.llm.chat(
                    messages=context,
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

            # 8️⃣ ⏱️ Measure the LLM turn.
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

            # 9️⃣ 💬 Save the assistant message.
            if response.assistant_message:
                state.add_message(response.assistant_message)

            # ! 🔟 ✅ No tool call = task is finished.
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

            # ======================================
            # ! 1️⃣1️⃣ 🔧 Run each requested tool.
            # ======================================
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

                # 🛡️ ToolExecutor handles:
                # - tool lookup
                # - argument validation
                # - tool execution
                # - error normalization
                tool_result = self.executor.execute(
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                )

                # 1️⃣2️⃣ ✂️ Prepare safe output for the LLM.
                result = truncate_output(
                    tool_result.output
                    if tool_result.success
                    else (
                        f"Tool '{tool_call.name}' failed.\n"
                        f"Error type: {tool_result.error_type}\n"
                        f"Error: {tool_result.error}"
                    )
                )

                # 1️⃣3️⃣ ⏱️ Measure tool execution time.
                tool_elapsed = time.monotonic() - tool_started_at

                # 1️⃣4️⃣ 👀 Observe the result.
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

                # 1️⃣5️⃣ 📢 Tell the UI what happened.
                emit(
                    AgentEvent(
                        kind="tool_end",
                        turn=turn,
                        tool_name=tool_call.name,
                        elapsed=tool_elapsed,
                        message=("ok" if tool_result.success else "error"),
                    )
                )

                # 1️⃣6️⃣ 🛠️ Try recovery if the tool failed.
                if not tool_result.success:
                    recovery_exception = RuntimeError(tool_result.error or "Unknown tool error.")

                    recovery_decision = self.recovery.recover(recovery_exception)

                    # ❌ Recovery says stop.
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

                        raise RuntimeError(message) from recovery_exception

                # e 1️⃣7️⃣ 📩 Send the tool result back to the LLM.
                state.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": observation.result,
                    }
                )

        # ! 1️⃣8️⃣ 🛑 Stop when max turns are reached.
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
