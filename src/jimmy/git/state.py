import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitSnapshot:
    """Git files that were changed at a specific moment."""

    changed_files: frozenset[str]


class GitState:
    """Tracks Git state from the beginning of a Jimmy session."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.baseline = self.snapshot()

    def snapshot(self) -> GitSnapshot:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=10,
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Failed to read Git status.")

        return GitSnapshot(changed_files=frozenset(self._parse_status(result.stdout)))

    def current_files(self) -> set[str]:
        return set(self.snapshot().changed_files)

    def preexisting_files(self) -> set[str]:
        return set(self.baseline.changed_files)

    def jimmy_files(self) -> set[str]:
        """
        Files that are changed now but were clean
        when Jimmy's session started.
        """
        return self.current_files() - self.preexisting_files()

    @staticmethod
    def _parse_status(output: str) -> set[str]:
        files: set[str] = set()

        for line in output.splitlines():
            if len(line) < 4:
                continue

            path = line[3:].strip()

            if not path:
                continue

            if " -> " in path:
                path = path.split(" -> ", 1)[1]

            files.add(path.replace("\\", "/"))

        return files
