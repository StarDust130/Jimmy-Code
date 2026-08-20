from typing import Any

import pytest

from jimmy.tools.base import Tool
from jimmy.tools.registry import ToolRegistry


class FakeTool(Tool):
    @property
    def name(self) -> str:
        return "fake_tool"

    @property
    def description(self) -> str:
        return "A fake tool for testing."

    def execute(self, arguments: dict[str, Any]) -> str:
        return "hello from fake tool"


def test_register_and_get_tool() -> None:
    registry = ToolRegistry()
    tool = FakeTool()

    registry.register(tool)

    assert registry.get("fake_tool") is tool


def test_get_unknown_tool() -> None:
    registry = ToolRegistry()

    with pytest.raises(KeyError, match="Unknown tool"):
        registry.get("does_not_exist")


def test_duplicate_tool_registration() -> None:
    registry = ToolRegistry()
    tool = FakeTool()

    registry.register(tool)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool)
