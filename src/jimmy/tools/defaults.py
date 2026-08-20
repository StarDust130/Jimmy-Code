from pathlib import Path

from jimmy.tools.edit_file import EditFileTool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.read_file import ReadFileTool
from jimmy.tools.registry import ToolRegistry
from jimmy.tools.search_files import SearchFilesTool


def create_default_registry(root: Path) -> ToolRegistry:
    filesystem = Filesystem(root)

    registry = ToolRegistry()

    registry.register(ReadFileTool(filesystem))
    registry.register(SearchFilesTool(filesystem))
    registry.register(EditFileTool(filesystem))

    return registry
