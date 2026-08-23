from typing import Any

from jimmy.tools.registry import ToolRegistry


class ToolExecutor:
    """Executes tool calls against the registered tool set."""

    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        tool = self.tools.get(tool_name)

        result = tool.execute(arguments)

        return str(result)
