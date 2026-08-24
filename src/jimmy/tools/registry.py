from typing import Any

from jimmy.tools.base import Tool


class ToolRegistry:
    """Stores and retrieves Jimmy tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")

        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        """Return tool definitions for the LLM."""

        schemas: list[dict[str, Any]] = []

        for tool in self._tools.values():
            parameters = tool.input_model.model_json_schema()

            parameters.pop(
                "title",
                None,
            )

            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": parameters,
                    },
                }
            )

        return schemas
