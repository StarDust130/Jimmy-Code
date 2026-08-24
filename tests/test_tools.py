import pytest
from pydantic import BaseModel

from jimmy.tools.base import Tool
from jimmy.tools.models import ToolMetadata, ToolResult
from jimmy.tools.registry import ToolRegistry


class FakeInput(BaseModel):
    value: str


class FakeTool(Tool):
    @property
    def name(self) -> str:
        return "fake_tool"

    @property
    def description(self) -> str:
        return "A fake tool for testing."

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata()

    @property
    def input_model(self) -> type[BaseModel]:
        return FakeInput

    def execute(self, arguments: BaseModel) -> ToolResult:
        args = FakeInput.model_validate(arguments)

        return ToolResult.ok(
            output=f"hello {args.value}",
        )


def test_register_and_get_tool() -> None:
    registry = ToolRegistry()
    tool = FakeTool()

    registry.register(tool)

    assert registry.get("fake_tool") is tool


def test_get_unknown_tool() -> None:
    registry = ToolRegistry()

    with pytest.raises(
        KeyError,
        match="Unknown tool",
    ):
        registry.get("does_not_exist")


def test_duplicate_tool_registration() -> None:
    registry = ToolRegistry()
    tool = FakeTool()

    registry.register(tool)

    with pytest.raises(
        ValueError,
        match="already registered",
    ):
        registry.register(tool)
