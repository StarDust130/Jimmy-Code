from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalTask:
    id: str
    prompt: str
    files: dict[str, str] = field(default_factory=dict)
    expected_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = ()
    expected_changed_files: tuple[str, ...] = ()
    expected_unmodified_files: tuple[str, ...] = ()
    test_command: str | None = None
    git: bool = True


TASKS: tuple[EvalTask, ...] = (
    EvalTask(
        "E01",
        "Read main.py and tell me what it does.",
        {"main.py": "print('hello')\n"},
        expected_tools=("read_file",),
        forbidden_tools=("edit_file", "create_files", "git_commit"),
    ),
    EvalTask(
        "E02",
        "Find where greeting is defined and tell me the file.",
        {"main.py": "def greeting():\n    return 'hello'\n"},
        expected_tools=("search_files",),
        forbidden_tools=("edit_file", "git_commit"),
    ),
    EvalTask(
        "E03",
        "Add a comment above greeting in main.py.",
        {"main.py": "def greeting():\n    return 'hello'\n"},
        expected_tools=("edit_file",),
        forbidden_tools=("create_files", "run_shell", "git_commit"),
        expected_changed_files=("main.py",),
    ),
    EvalTask(
        "E04",
        "Create hello.txt containing exactly: hello Jimmy",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("run_shell", "git_commit"),
        expected_changed_files=("hello.txt",),
    ),
    EvalTask(
        "E05",
        "Create index.html, style.css, and script.js for a small page.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("git_commit",),
        expected_changed_files=("index.html", "style.css", "script.js"),
    ),
    EvalTask(
        "E06",
        "Run the test suite.",
        {"test_pass.py": "def test_ok():\n    assert 1 + 1 == 2\n"},
        expected_tools=("run_shell",),
        forbidden_tools=("edit_file", "create_files", "git_commit"),
        test_command="uv run pytest -q",
    ),
    EvalTask(
        id="E07",
        prompt="Create a cool tiny browser game using HTML, CSS, and JavaScript.",
        files={
            "README.md": "# Game Project\n",
        },
    ),
    EvalTask(
        "E08",
        "Improve the existing browser game by adding double jump and better styling.",
        {
            "index.html": "<!doctype html>\n<html><body><script src='script.js'></script></body></html>\n",
            "style.css": "body { background: #000; }\n",
            "script.js": "let jumps = 1;\n",
        },
        expected_tools=("edit_file",),
        forbidden_tools=("create_files", "git_commit"),
        expected_changed_files=("index.html", "style.css", "script.js"),
    ),
    EvalTask(
        "E09",
        "Commit main.py only.",
        {"main.py": "print('changed')\n", "other.py": "print('other')\n"},
        expected_tools=("git_commit",),
        forbidden_tools=("run_shell",),
        expected_unmodified_files=("other.py",),
    ),
    EvalTask(
        "E10",
        "Commit all changed files one by one.",
        {"a.py": "print('a')\n", "b.py": "print('b')\n", "c.py": "print('c')\n"},
        expected_tools=("git_commit",),
        forbidden_tools=("run_shell",),
    ),
    EvalTask(
        "E11",
        "Add a comment to main.py. Do not commit anything.",
        {"main.py": "print('hello')\n"},
        expected_tools=("edit_file",),
        forbidden_tools=("git_commit",),
        expected_changed_files=("main.py",),
    ),
    EvalTask(
        "E12",
        "Create app.py with a hello command.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("run_shell", "git_commit"),
        expected_changed_files=("app.py",),
    ),
    EvalTask(
        "E13",
        "Add a function to utils.py without changing anything else.",
        {"utils.py": "def existing():\n    return 1\n", "README.md": "# Project\n"},
        expected_tools=("read_file", "edit_file"),
        forbidden_tools=("git_commit",),
        expected_changed_files=("utils.py",),
        expected_unmodified_files=("README.md",),
    ),
    EvalTask(
        "E14",
        "Tell me the current Git status.",
        {"main.py": "print('hello')\n"},
        expected_tools=("run_shell",),
        forbidden_tools=("edit_file", "git_commit"),
    ),
    EvalTask(
        "E15",
        "Fix this typo in README.md: 'teh' should become 'the'.",
        {"README.md": "# Title\nThis is teh project.\n"},
        expected_tools=("edit_file",),
        forbidden_tools=("create_files", "git_commit", "run_shell"),
        expected_changed_files=("README.md",),
    ),
    EvalTask(
        "E16",
        "Create a simple Python package with __init__.py and calculator.py.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("git_commit",),
        expected_changed_files=("mypkg/__init__.py", "mypkg/calculator.py"),
    ),
    EvalTask(
        "E17",
        "Read config.py and tell me which setting controls the port.",
        {"config.py": "PORT = 8000\nDEBUG = True\n"},
        expected_tools=("read_file",),
        forbidden_tools=("edit_file", "git_commit"),
    ),
    EvalTask(
        "E18",
        "Create a README.md with a title and one sentence.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("git_commit",),
        expected_changed_files=("README.md",),
    ),
    EvalTask(
        "E19",
        "Run the tests, and if they fail fix the failure then run them again.",
        {
            "math_utils.py": ("def add(a, b):\n    return a - b\n"),
            "test_math.py": (
                "from math_utils import add\n\n\ndef test_add():\n    assert add(1, 1) == 2\n"
            ),
        },
        expected_tools=(
            "run_shell",
            "read_file",
            "edit_file",
        ),
        forbidden_tools=(
            "git_commit",
            "create_files",
        ),
        expected_changed_files=("math_utils.py",),
    ),
    EvalTask(
        "E20",
        "Read main.py and continue from the current state.",
        {"main.py": "def main():\n    print('resume me')\n"},
        expected_tools=("read_file",),
        forbidden_tools=("git_commit",),
    ),
)
