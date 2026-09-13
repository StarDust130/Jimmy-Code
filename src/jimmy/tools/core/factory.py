# 🔧 Built-in tools Jimmy can use
from .builtin.edit_files import EditFilesTool
from .builtin.read_files import ReadFilesTool
from .builtin.search_files import SearchFilesTool
from .builtin.shell import ShellTool

# 📋 Tool registry
from .core.registry import ToolRegistry


def create_default_registry() -> ToolRegistry:
    # 📦 Create the registry
    registry = ToolRegistry()

    # 🛠️ Register Jimmy's default tools
    registry.register(ReadFilesTool())
    registry.register(SearchFilesTool())
    registry.register(EditFilesTool())
    registry.register(ShellTool())

    # 📤 Return the ready-to-use registry
    return registry