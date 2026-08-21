from jimmy.llm.base import LLMProvider
from jimmy.state.session import SessionState
from jimmy.tools.registry import ToolRegistry

SYSTEM_PROMPT = """You are Jimmy🕺, a terminal-native coding agent.

You work inside the user's current project.

Use the available tools to inspect files, search code, edit files,
and run commands when needed.

Do not claim you changed something unless you actually used a tool
to make the change.

Keep working until the task is complete.
"""


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

    def run(self, task: str) -> str:
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

            print(f"\n🧠 Turn {turn}")

            response = self.llm.chat(
                messages=state.messages,
                tools=tool_schemas,
            )

            if response.assistant_message:
                state.add_message(response.assistant_message)

            if not response.tool_calls:
                return response.content or ""

            for tool_call in response.tool_calls:
                print(f"🔧 Tool used: {tool_call.name}")

                try:
                    tool = self.tools.get(tool_call.name)

                    result = tool.execute(tool_call.arguments)

                except Exception as exc:
                    result = f"Tool error: {type(exc).__name__}: {exc}"

                state.add_message(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": str(result),
                    }
                )

        raise RuntimeError(f"Jimmy stopped after reaching the {self.max_turns}-turn limit.")
