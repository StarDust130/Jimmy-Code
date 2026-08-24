from typing import Any

from pydantic import ValidationError

from jimmy.tools.models import ToolResult
from jimmy.tools.registry import ToolRegistry


class ToolExecutor:
    """Validates and executes tools."""

    def __init__(self, tools: ToolRegistry) -> None:
        self.tools = tools

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        tool = self.tools.get(tool_name)

        try:
            validated_arguments = tool.input_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult.fail(
                error_type="validation_error",
                error="Invalid tool arguments.",
                metadata={
                    "details": exc.errors(),
                    "tool": tool_name,
                },
            )

        try:
            result = tool.execute(validated_arguments)

            if not isinstance(result, ToolResult):
                return ToolResult.fail(
                    error_type="invalid_tool_result",
                    error=(f"Tool '{tool_name}' returned an invalid result type."),
                    metadata={
                        "tool": tool_name,
                    },
                )

            return result

        except (
            ValueError,
            TypeError,
            OSError,
            RuntimeError,
            TimeoutError,
            PermissionError,
            FileNotFoundError,
        ) as exc:
            return ToolResult.fail(
                error_type=type(exc).__name__,
                error=str(exc),
                metadata={
                    "tool": tool_name,
                },
            )
