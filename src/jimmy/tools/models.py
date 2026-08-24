from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolMetadata(BaseModel):
    """Operational information about a tool."""

    model_config = ConfigDict(extra="forbid")

    read_only: bool = True
    destructive: bool = False
    requires_confirmation: bool = False
    timeout_seconds: float | None = None


class ToolResult(BaseModel):
    """Standard result returned by every tool."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    output: str = ""
    error_type: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(
        cls,
        output: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            success=True,
            output=output,
            metadata=metadata or {},
        )

    @classmethod
    def fail(
        cls,
        error_type: str,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        return cls(
            success=False,
            error_type=error_type,
            error=error,
            metadata=metadata or {},
        )
