from pathlib import Path

from jimmy.exploration.explorer import CodebaseExplorer
from jimmy.exploration.fingerprint import build_fingerprint


def test_detects_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='example'\n",
        encoding="utf-8",
    )

    (tmp_path / "main.py").write_text(
        "print('hello')\n",
        encoding="utf-8",
    )

    (tmp_path / "tests").mkdir()

    fingerprint = build_fingerprint(tmp_path)

    assert "Python" in fingerprint.languages
    assert "Python" in fingerprint.frameworks
    assert "pyproject.toml" in fingerprint.config_files
    assert "tests" in fingerprint.test_directories


def test_explorer_builds_tree(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()

    (tmp_path / "src" / "main.py").write_text(
        "print('hello')\n",
        encoding="utf-8",
    )

    explorer = CodebaseExplorer(tmp_path)

    result = explorer.explore()

    assert "src" in result.tree
    assert "src/main.py" in result.tree
