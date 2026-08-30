from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from jimmy.tools.models import ToolResult
from jimmy.tools.registry import ToolRegistry


class ToolExecutor:
    """
    Validate and execute one tool call.

    Responsibilities:
    - resolve the requested tool
    - validate arguments using the tool's Pydantic model
    - execute the tool
    - normalize expected execution errors into ToolResult
    - never call the LLM
    - never make tool-selection decisions
    """

    def __init__(
        self,
        tools: ToolRegistry,
    ) -> None:
        self.tools = tools

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        # --------------------------------------------------
        # 1. Resolve tool
        # --------------------------------------------------

        try:
            tool = self.tools.get(
                tool_name,
            )
        except Exception as exc:
            return ToolResult.fail(
                error_type="tool_not_found",
                error=(f"Unable to resolve tool '{tool_name}': {exc}"),
                metadata={
                    "tool": tool_name,
                },
            )

        # --------------------------------------------------
        # 2. Validate arguments
        # --------------------------------------------------

        try:
            validated_arguments = tool.input_model.model_validate(
                arguments,
            )

        except ValidationError as exc:
            return ToolResult.fail(
                error_type="validation_error",
                error=(f"Invalid arguments for tool '{tool_name}'."),
                metadata={
                    "tool": tool_name,
                    "details": exc.errors(),
                },
            )

        except (TypeError, ValueError) as exc:
            return ToolResult.fail(
                error_type="validation_error",
                error=(f"Invalid arguments for tool '{tool_name}': {exc}"),
                metadata={
                    "tool": tool_name,
                },
            )

        # --------------------------------------------------
        # 3. Execute tool
        # --------------------------------------------------

        try:
            result = tool.execute(
                validated_arguments,
            )

        # --------------------------------------------------
        # 4. Convert expected tool failures into a result
        # --------------------------------------------------

        except FileNotFoundError as exc:
            return ToolResult.fail(
                error_type="FileNotFoundError",
                error=str(exc),
                metadata={
                    "tool": tool_name,
                },
            )

        except PermissionError as exc:
            return ToolResult.fail(
                error_type="PermissionError",
                error=str(exc),
                metadata={
                    "tool": tool_name,
                },
            )

        except TimeoutError as exc:
            return ToolResult.fail(
                error_type="TimeoutError",
                error=str(exc),
                metadata={
                    "tool": tool_name,
                },
            )

        except OSError as exc:
            return ToolResult.fail(
                error_type="OSError",
                error=str(exc),
                metadata={
                    "tool": tool_name,
                },
            )

        except ValueError as exc:
            return ToolResult.fail(
                error_type="ValueError",
                error=str(exc),
                metadata={
                    "tool": tool_name,
                },
            )

        except TypeError as exc:
            return ToolResult.fail(
                error_type="TypeError",
                error=str(exc),
                metadata={
                    "tool": tool_name,
                },
            )

        except RuntimeError as exc:
            return ToolResult.fail(
                error_type="RuntimeError",
                error=str(exc),
                metadata={
                    "tool": tool_name,
                },
            )

        # --------------------------------------------------
        # 5. Never let an unexpected exception silently
        #    crash the entire agent.
        # --------------------------------------------------

        except Exception as exc:
            return ToolResult.fail(
                error_type=type(exc).__name__,
                error=(f"Unexpected error in tool '{tool_name}': {exc}"),
                metadata={
                    "tool": tool_name,
                },
            )

        # --------------------------------------------------
        # 6. Enforce ToolResult contract
        # --------------------------------------------------

        if not isinstance(
            result,
            ToolResult,
        ):
            return ToolResult.fail(
                error_type="invalid_tool_result",
                error=(
                    f"Tool '{tool_name}' returned {type(result).__name__} instead of ToolResult."
                ),
                metadata={
                    "tool": tool_name,
                    "returned_type": (type(result).__name__),
                },
            )

        return result
