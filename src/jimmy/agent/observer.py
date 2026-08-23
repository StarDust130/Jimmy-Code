from dataclasses import dataclass


@dataclass
class ToolObservation:
    """Result of executing a tool."""

    tool_name: str
    success: bool
    result: str


class Observer:
    """Converts tool execution results into agent observations."""

    def observe_success(
        self,
        tool_name: str,
        result: str,
    ) -> ToolObservation:
        return ToolObservation(
            tool_name=tool_name,
            success=True,
            result=result,
        )

    def observe_failure(
        self,
        tool_name: str,
        error: Exception,
    ) -> ToolObservation:
        return ToolObservation(
            tool_name=tool_name,
            success=False,
            result=(
                f"🔨 Tool '{tool_name}' failed😭.\nError type: {type(error).__name__}\nError: {error}"
            ),
        )
