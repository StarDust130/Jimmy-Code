from pathlib import Path


class Filesystem:
    """Provides safe access to the Jimmy working directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def resolve_path(self, path: str) -> Path:
        """Resolve a user-provided path inside the working directory."""
        candidate = (self.root / path).resolve()

        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Path is outside the working directory: {path}") from exc

        return candidate
