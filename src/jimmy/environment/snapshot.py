from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    """Small deterministic snapshot of the current workspace."""

    cwd: str
    os_name: str
    shell: str
    git_branch: str | None
    git_status: str
    top_level_entries: tuple[str, ...]
    instruction_files: tuple[str, ...]
    project_markers: tuple[str, ...]

    def to_prompt(self) -> str:
        """
        Render only compact, useful environment facts.

        This is intentionally small. The model should use tools to
        discover detailed repository contents.
        """

        lines = [
            "<environment_context>",
            f"cwd: {self.cwd}",
            f"os: {self.os_name}",
            f"shell: {self.shell}",
        ]

        if self.git_branch:
            lines.append(
                f"git_branch: {self.git_branch}",
            )

        lines.append(
            f"git_status: {self.git_status or 'clean'}",
        )

        if self.top_level_entries:
            lines.append(
                "top_level: "
                + ", ".join(self.top_level_entries),
            )

        if self.instruction_files:
            lines.append(
                "project_instructions: "
                + ", ".join(self.instruction_files),
            )

        if self.project_markers:
            lines.append(
                "project_markers: "
                + ", ".join(self.project_markers),
            )

        lines.append(
            "</environment_context>",
        )

        return "\n".join(lines)


class EnvironmentInspector:
    """
    Collect cheap, deterministic workspace facts.

    Important:
    - no LLM
    - no recursive repository scan
    - no full-file reads
    - no expensive commands
    """

    _INSTRUCTION_NAMES = (
        "AGENTS.md",
        "AGENTS.override.md",
        "CLAUDE.md",
        "CODEX.md",
        "README.md",
        "JIMMY.md",
    )

    _PROJECT_MARKERS = (
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "Makefile",
        "CMakeLists.txt",
        "requirements.txt",
        "uv.lock",
        "poetry.lock",
        "pnpm-lock.yaml",
        "yarn.lock",
        "package-lock.json",
    )

    def __init__(
        self,
        workspace: Path,
    ) -> None:
        self.workspace = workspace.resolve()

    def snapshot(self) -> EnvironmentSnapshot:
        return EnvironmentSnapshot(
            cwd=str(self.workspace),
            os_name=os.name,
            shell=self._shell_name(),
            git_branch=self._git_branch(),
            git_status=self._git_status(),
            top_level_entries=self._top_level_entries(),
            instruction_files=self._instruction_files(),
            project_markers=self._project_markers(),
        )

    # =========================================================
    # SHELL
    # =========================================================

    @staticmethod
    def _shell_name() -> str:
        shell = os.environ.get("SHELL")

        if shell:
            return Path(shell).name

        if os.name == "nt":
            return "cmd"

        return "unknown"

    # =========================================================
    # GIT
    # =========================================================

    def _git_branch(self) -> str | None:
        result = self._run_git(
            "branch",
            "--show-current",
        )

        if result is None:
            return None

        branch = result.strip()

        return branch or None

    def _git_status(self) -> str:
        result = self._run_git(
            "status",
            "--short",
        )

        if result is None:
            return "not-a-git-repository"

        return result.strip()

    def _run_git(
        self,
        *args: str,
    ) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=2.0,
            )
        except (
            OSError,
            subprocess.TimeoutExpired,
        ):
            return None

        if result.returncode != 0:
            return None

        return result.stdout

    # =========================================================
    # FILESYSTEM
    # =========================================================

    def _top_level_entries(
        self,
    ) -> tuple[str, ...]:
        try:
            entries = sorted(
                entry.name
                for entry in self.workspace.iterdir()
                if entry.name != ".git"
            )
        except OSError:
            return ()

        # Keep the environment message bounded.
        return tuple(entries[:40])

    def _instruction_files(
        self,
    ) -> tuple[str, ...]:
        found: list[str] = []

        # Only inspect a small number of conventional locations.
        # Do not recursively search the repository here.
        candidates = (
            self.workspace,
            self.workspace / ".github",
            self.workspace / ".claude",
            self.workspace / ".codex",
        )

        for directory in candidates:
            for name in self._INSTRUCTION_NAMES:
                path = directory / name

                if path.is_file():
                    found.append(
                        str(
                            path.relative_to(
                                self.workspace,
                            ),
                        ),
                    )

        return tuple(
            sorted(
                set(found),
            ),
        )

    def _project_markers(
        self,
    ) -> tuple[str, ...]:
        found: list[str] = []

        for name in self._PROJECT_MARKERS:
            if (self.workspace / name).exists():
                found.append(name)

        return tuple(found)