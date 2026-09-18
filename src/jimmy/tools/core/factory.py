"""🔧 Built-in tools Jimmy can use.

Selection philosophy:
  🌳 list_files   — understand structure (cheaper than shell ls -R)
  🔍 search_files — find text/files
  📖 read_files   — inspect contents
  ✏️ edit_files   — small precise replacements
  🩹 apply_patch  — MULTI-hunk edits in one call
  ✍️ write_file   — create new files (refuses clobbering)
  🌿 git          — safe status/diff/add/commit/log (no push/reset)
  🧪 run_tests    — verify changes with a SUMMARY, not a firehose
  💻 shell        — escape hatch for everything else

Descriptions tell the model when NOT to use each tool — that is what
prevents tool-sprawl and wasted tokens.
"""

from ..builtin.apply_patch import ApplyPatchTool
from ..builtin.edit_files import EditFilesTool
from ..builtin.git_tool import GitTool
from ..builtin.list_files import ListFilesTool
from ..builtin.read_files import ReadFilesTool
from ..builtin.run_tests import RunTestsTool
from ..builtin.search_files import SearchFilesTool
from ..builtin.shell import ShellTool
from ..builtin.write_file import WriteFileTool
from ..core.registry import ToolRegistry


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(ListFilesTool())  # 🌳 understand project structure
    registry.register(SearchFilesTool())  # 🔍 find text/files
    registry.register(ReadFilesTool())  # 📖 inspect contents
    registry.register(EditFilesTool())  # ✏️ small precise replacements
    registry.register(ApplyPatchTool())  # 🩹 multi-location edits
    registry.register(WriteFileTool())  # ✍️ create new files
    registry.register(GitTool())  # 🌿 status / diff / add / commit / log
    registry.register(RunTestsTool())  # 🧪 verify changes
    registry.register(ShellTool())  # 💻 escape hatch

    return registry
