from pathlib import Path

from jimmy.agent.executor import ToolExecutor
from jimmy.tools.defaults import create_default_registry


def test_executor_validates_tool_arguments(
    tmp_path: Path,
) -> None:
    registry = create_default_registry(tmp_path)
    executor = ToolExecutor(registry)

    result = executor.execute(
        tool_name="read_file",
        arguments={},
    )

    assert result.success is False
    assert result.error_type == "validation_error"


def test_executor_returns_structured_success(
    tmp_path: Path,
) -> None:
    file = tmp_path / "example.txt"
    file.write_text(
        "hello Jimmy",
        encoding="utf-8",
    )

    registry = create_default_registry(tmp_path)
    executor = ToolExecutor(registry)

    result = executor.execute(
        tool_name="read_file",
        arguments={
            "path": "example.txt",
        },
    )

    assert result.success is True
    assert result.output == "hello Jimmy"
    assert result.metadata["path"] == "example.txt"


def test_executor_returns_structured_failure(
    tmp_path: Path,
) -> None:
    registry = create_default_registry(tmp_path)
    executor = ToolExecutor(registry)

    result = executor.execute(
        tool_name="read_file",
        arguments={
            "path": "missing.txt",
        },
    )

    assert result.success is False
    assert result.error_type == "FileNotFoundError"
