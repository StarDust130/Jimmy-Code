from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict


class ToolResult(BaseModel):
    """Result returned by every tool."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    output: str
    error: str | None = None


class Tool(ABC):
    """Base contract for every Jimmy tool."""

    name: str
    description: str
    args_schema: type[BaseModel]

    @abstractmethod
    def execute(self, arguments: BaseModel) -> ToolResult:
        """Execute the tool."""
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        """Return the tool schema that will later be given to the LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.args_schema.model_json_schema(),
        }