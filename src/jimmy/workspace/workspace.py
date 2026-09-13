"""Small workspace abstraction used by the runtime later."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path

    @classmethod
    def from_cwd(cls) -> "Workspace":
        return cls(root=Path.cwd().resolve())
