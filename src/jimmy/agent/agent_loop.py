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
from jimmy.tools.routing import is_commit_request
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

        # ======================================
        # 1️⃣ INITIAL SETUP
        # ======================================

        # 🔎 Detect commit-only workflow.
        is_commit = is_commit_request(task)

        # 📋 Plan + 🧭 explore only when needed.
        if is_commit:
            plan_state = None
            exploration_summary = ""
        else:
            plan_state = self.planner.create_initial_plan(task)
            exploration_summary = self.explorer.summary()

        # ======================================
        # 2️⃣ BUILD INITIAL CONTEXT
        # ======================================

        # 💬 Commit tasks need only the essential context.
        if is_commit:
            messages: list[dict[str, str]] = [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": task,
                },
            ]
        else:
            messages = [
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

            # 📋 Add plan only for normal tasks.
            if plan_state is not None:
                messages.append(
                    {
                        "role": "system",
                        "content": (f"Current execution plan:\n{plan_state.summary()}"),
                    }
                )

        # 🧠 Create session state.
        state = SessionState(
            task=task,
            messages=messages,
        )

        # ======================================
        # 3️⃣ PREPARE AVAILABLE TOOLS
        # ======================================

        all_tool_schemas = self.tools.schemas()

        if is_commit:
            # 🔐 Commit workflow exposes ONLY git_commit.
            tool_schemas = [
                schema for schema in all_tool_schemas if schema["function"]["name"] == "git_commit"
            ]

            # ❌ Fail early if git_commit is not registered.
            if not tool_schemas:
                raise RuntimeError("git_commit tool is required for commit tasks.")
        else:
            # 🛠️ Normal tasks can use all registered tools.
            tool_schemas = all_tool_schemas

        # ======================================
        # 4️⃣ MAIN AGENT LOOP
        # ======================================

        while state.turn_count < self.max_turns:
            turn = state.next_turn()
            turn_started_at = time.monotonic()

            emit(
                AgentEvent(
                    kind="turn_start",
                    turn=turn,
                )
            )

            # ======================================
            # 5️⃣ ASK LLM
            # ======================================

            # 🤖 Prepare context.
            try:
                context = self.context_manager.prepare(
                    state.messages,
                )

                # 🎯 Force git_commit on the first commit turn.
                tool_choice = (
                    {
                        "type": "function",
                        "function": {
                            "name": "git_commit",
                        },
                    }
                    if is_commit and turn == 1
                    else None
                )

                response = self.llm.chat(
                    messages=context,
                    tools=tool_schemas,
                    tool_choice=tool_choice,
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

            # ======================================
            # 6️⃣ HANDLE LLM TURN
            # ======================================

            # ⏱️ Measure LLM turn.
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

            # 💬 Save assistant response.
            if response.assistant_message:
                state.add_message(response.assistant_message)

            # ✅ No tool calls = task finished.
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
            # 7️⃣ EXECUTE TOOLS
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

                # ======================================
                # 8️⃣ PREPARE TOOL RESULT
                # ======================================

                # ✂️ Limit output before sending it to the LLM.
                result = truncate_output(
                    tool_result.output
                    if tool_result.success
                    else (
                        f"Tool '{tool_call.name}' failed.\n"
                        f"Error type: {tool_result.error_type}\n"
                        f"Error: {tool_result.error}"
                    )
                )

                # ⏱️ Measure tool execution time.
                tool_elapsed = time.monotonic() - tool_started_at

                # ======================================
                # 9️⃣ OBSERVE TOOL RESULT
                # ======================================

                # 👀 Observe success or failure.
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

                # 📢 Tell the UI what happened.
                emit(
                    AgentEvent(
                        kind="tool_end",
                        turn=turn,
                        tool_name=tool_call.name,
                        elapsed=tool_elapsed,
                        message=("ok" if tool_result.success else "error"),
                    )
                )

                # ======================================
                # 🔟 RECOVERY
                # ======================================

                # 🛠️ Try recovery when the tool fails.
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

                # ======================================
                # 1️⃣1️⃣ SAVE TOOL RESULT
                # ======================================

                # 📩 Send observation back into conversation state.
                state.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": observation.result,
                    }
                )

                # ======================================
                # 1️⃣2️⃣ EARLY TASK COMPLETION
                # ======================================

                # ✅ A final tool can explicitly stop the agent.
                if (
                    tool_call.name == "git_commit"
                    and tool_result.success
                    and tool_result.metadata.get("task_complete") is True
                ):
                    total_elapsed = time.monotonic() - started_at
                    final_message = tool_result.output

                    emit(
                        AgentEvent(
                            kind="complete",
                            turn=turn,
                            elapsed=total_elapsed,
                            message=final_message,
                        )
                    )

                    return final_message

        # ======================================
        # 1️⃣3️⃣ MAX TURNS REACHED
        # ======================================

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
