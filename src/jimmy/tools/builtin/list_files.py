"""🌳 ListFilesTool — understand the project structure in ONE call."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..core.base import Tool, ToolResult

# 🚫 never descend into these — generated/dependency noise
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    ".next",
    "target",
    "coverage",
}

# 🖼️/📦 files that are never text — show as [binary], don't read
SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".whl",
    ".exe",
    ".dll",
    ".so",
    ".mp3",
    ".mp4",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
}


class ListFilesArgs(BaseModel):
    """Arguments for the tree listing."""

    path: str = Field(
        default=".",
        description="Directory to list (relative to workspace). Use '.' for root.",
    )
    max_depth: int = Field(
        default=3,
        ge=1,
        le=8,
        description="How deep to walk. 1 = this folder only.",
    )
    show_size: bool = Field(
        default=False,
        description="Include file sizes (bytes) — useful before reading.",
    )


class ListFilesTool(Tool):
    name = "list_files"
    description = (
        "List the workspace file tree. Use this FIRST when you need to "
        "understand the project structure — it is cheaper than running "
        "'ls -R' through shell. Skips .git, node_modules, __pycache__ and "
        "other generated folders. Do NOT use it to find text inside files "
        "(use search_files for that)."
    )
    args_schema = ListFilesArgs

    def execute(self, arguments: ListFilesArgs) -> ToolResult:
        workspace = Path.cwd().resolve()
        root = (workspace / arguments.path).resolve()

        # 🔒 workspace guard
        try:
            root.relative_to(workspace)
        except ValueError:
            return ToolResult(
                success=False,
                output="",
                error=f"Path is outside workspace: {arguments.path}",
            )

        if not root.exists():
            return ToolResult(
                success=False,
                output="",
                error=f"Path does not exist: {arguments.path}",
            )
        if not root.is_dir():
            return ToolResult(
                success=False,
                output="",
                error=f"Not a directory: {arguments.path}",
            )

        lines: list[str] = []
        total_files = 0
        truncated = False

        def walk(directory: Path, prefix: str, depth: int) -> None:
            nonlocal total_files, truncated

            if depth > arguments.max_depth:
                return

            try:
                entries = sorted(
                    directory.iterdir(),
                    key=lambda p: (p.is_file(), p.name.lower()),
                )
            except OSError:
                return

            for entry in entries:
                if total_files >= 400:  # 🛑 hard safety cap
                    nonlocal_prefix = "…"
                    if not truncated:
                        lines.append(f"{prefix}… (output capped at 400 entries)")
                        truncated = True
                    del nonlocal_prefix
                    return

                name = entry.name

                if entry.is_dir():
                    if name in IGNORED_DIRS or name.startswith(".git"):
                        continue
                    lines.append(f"{prefix}{name}/")
                    walk(entry, prefix + "  ", depth + 1)
                    continue

                if entry.suffix.lower() in SKIP_SUFFIXES:
                    continue

                total_files += 1
                if arguments.show_size:
                    try:
                        size = entry.stat().st_size
                        lines.append(f"{prefix}{name}  ({size} B)")
                    except OSError:
                        lines.append(f"{prefix}{name}")
                else:
                    lines.append(f"{prefix}{name}")

        label = arguments.path
        lines.append(f"{label}/")
        walk(root, "", 1)

        if len(lines) <= 1:
            return ToolResult(
                success=True,
                output=f"{label}/ (empty or nothing listable)",
            )

        note = ""
        if truncated:
            note = "\n\n(output capped — narrow with `path` or lower `max_depth`)"

        return ToolResult(
            success=True,
            output="\n".join(lines) + note,
        )
