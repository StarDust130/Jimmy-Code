from pathlib import Path

from jimmy.exploration.fingerprint import build_fingerprint
from jimmy.exploration.models import ExplorationResult

IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


class CodebaseExplorer:
    """Collects a lightweight map of the current repository."""

    def __init__(
        self,
        root: Path,
        max_tree_entries: int = 300,
    ) -> None:
        self.root = root.resolve()
        self.max_tree_entries = max_tree_entries

    def explore(self) -> ExplorationResult:
        fingerprint = build_fingerprint(self.root)

        tree = self._build_tree()

        return ExplorationResult(
            fingerprint=fingerprint,
            tree=tree,
        )

    def _build_tree(self) -> list[str]:
        entries: list[str] = []

        for path in sorted(self.root.rglob("*")):
            if any(part in IGNORED_DIRECTORIES for part in path.parts):
                continue

            relative = path.relative_to(self.root)

            entries.append(relative.as_posix())

            if len(entries) >= self.max_tree_entries:
                break

        return entries

    def summary(self) -> str:
        result = self.explore()

        fingerprint = result.fingerprint

        lines = [
            f"Workspace: {fingerprint.root}",
            "",
            f"Languages: {', '.join(fingerprint.languages) or 'unknown'}",
            f"Frameworks: {', '.join(fingerprint.frameworks) or 'unknown'}",
            (f"Package managers: {', '.join(fingerprint.package_managers) or 'unknown'}"),
            (f"Config files: {', '.join(fingerprint.config_files) or 'none'}"),
            (f"Test directories: {', '.join(fingerprint.test_directories) or 'none'}"),
            (f"Important files: {', '.join(fingerprint.important_files) or 'none'}"),
            "",
            "Top-level tree:",
        ]

        lines.extend(f"- {entry}" for entry in result.tree)

        return "\n".join(lines)
