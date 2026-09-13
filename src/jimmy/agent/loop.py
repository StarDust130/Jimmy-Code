"""Jimmy's core tool-using agent loop."""

from collections.abc import AsyncIterator

from jimmy.context import ContextBuilder
from jimmy.llm.provider import LLMProvider
from jimmy.llm.types import Message
from jimmy.tools.core.factory import create_default_registry
from jimmy.tools.core.registry import ToolRegistry


class Agent:
    """Runs the LLM ↔ tool loop."""

    def __init__(
        self,
        provider: LLMProvider,
        context: ContextBuilder | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        # 1️⃣ Store the AI provider
        self.provider = provider

        # 2️⃣ Create context manager
        self.context = context or ContextBuilder()

        # 3️⃣ Load available tools
        self.tools = tools or create_default_registry()

        # 4️⃣ Keep conversation history
        self.history: list[Message] = []

    async def stream(self, user_text: str) -> AsyncIterator[str]:
        # 5️⃣ Build the initial context for the request
        messages = self.context.build(user_text, self.history)

        # 6️⃣ Keep working until the task is finished
        while True:
            # 7️⃣ Ask the model what to do
            result = await self.provider.complete(
                messages,
                tools=self.tools.schemas(),
            )

            # 8️⃣ No tool needed → return the final answer
            if not result.tool_calls:
                answer = result.content

                # 9️⃣ Save the conversation
                self.history.append(Message(role="user", content=user_text))
                self.history.append(Message(role="assistant", content=answer))

                # 🔟 Send the answer to the UI
                if answer:
                    yield answer

                return

            # 1️⃣1️⃣ Save the model's tool request
            messages.append(
                Message(
                    role="assistant",
                    content=result.content or "",
                    tool_calls=result.tool_calls,
                )
            )

            # 1️⃣2️⃣ Execute every requested tool
            for call in result.tool_calls:
                # 🔎 Find the requested tool
                tool = self.tools.get(call.name)

                # ✅ Validate tool arguments
                arguments = tool.args_schema.model_validate(call.arguments)

                # ⚙️ Run the tool
                tool_result = tool.execute(arguments)

                # 1️⃣3️⃣ Send the tool result back to the model
                messages.append(
                    Message(
                        role="tool",
                        content=tool_result.output,
                        tool_call_id=call.id,
                    )
                )
