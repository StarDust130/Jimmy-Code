from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EvalTask:
    id: str
    prompt: str

    files: dict[str, str] = field(
        default_factory=dict,
    )

    expected_tools: tuple[str, ...] = ()

    forbidden_tools: tuple[str, ...] = ()

    expected_changed_files: tuple[str, ...] = ()

    expected_unmodified_files: tuple[str, ...] = ()

    test_command: str | None = None

    git: bool = True

    # --------------------------------------------------------
    # Efficiency measurement.
    #
    # These are measurement targets, NOT hard requirements.
    #
    # A task can still pass when the agent exceeds the target.
    # The eval report simply tells us that the agent was slower
    # or more tool-heavy than expected.
    # --------------------------------------------------------

    efficiency_max_tools: int | None = None

    efficiency_max_turns: int | None = None


TASKS: tuple[EvalTask, ...] = (
    EvalTask(
        "E01",
        "Read main.py and tell me what it does.",
        {"main.py": "print('hello')\n"},
        expected_tools=("read_file",),
        forbidden_tools=(
            "edit_file",
            "create_files",
            "git_commit",
        ),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E02",
        "Find where greeting is defined and tell me the file.",
        {"main.py": "def greeting():\n    return 'hello'\n"},
        expected_tools=("search_files",),
        forbidden_tools=(
            "edit_file",
            "git_commit",
        ),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E03",
        "Add a comment above greeting in main.py.",
        {"main.py": "def greeting():\n    return 'hello'\n"},
        expected_tools=("edit_file",),
        forbidden_tools=(
            "create_files",
            "run_shell",
            "git_commit",
        ),
        expected_changed_files=("main.py",),
        efficiency_max_tools=2,
        efficiency_max_turns=3,
    ),
    EvalTask(
        "E04",
        "Create hello.txt containing exactly: hello Jimmy",
        {},
        expected_tools=("create_files",),
        forbidden_tools=(
            "run_shell",
            "git_commit",
        ),
        expected_changed_files=("hello.txt",),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E05",
        "Create index.html, style.css, and script.js for a small page.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("git_commit",),
        expected_changed_files=(
            "index.html",
            "style.css",
            "script.js",
        ),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E06",
        "Run the test suite.",
        {"test_pass.py": "def test_ok():\n    assert 1 + 1 == 2\n"},
        expected_tools=("run_shell",),
        forbidden_tools=(
            "edit_file",
            "create_files",
            "git_commit",
        ),
        test_command="uv run pytest -q",
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E07",
        "Create a cool tiny browser game using HTML, CSS, and JavaScript.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("git_commit",),
        expected_changed_files=(
            "index.html",
            "style.css",
            "script.js",
        ),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E08",
        "Improve the existing browser game by adding double jump and better styling.",
        {
            "index.html": (
                "<!doctype html>\n<html><body><script src='script.js'></script></body></html>\n"
            ),
            "style.css": ("body { background: #000; }\n"),
            "script.js": ("let jumps = 1;\n"),
        },
        expected_tools=("edit_file",),
        forbidden_tools=(
            "create_files",
            "git_commit",
        ),
        expected_changed_files=(
            "index.html",
            "style.css",
            "script.js",
        ),
        efficiency_max_tools=4,
        efficiency_max_turns=6,
    ),
    EvalTask(
        "E09",
        "Commit main.py only.",
        {
            "main.py": "print('changed')\n",
            "other.py": "print('other')\n",
        },
        expected_tools=("git_commit",),
        forbidden_tools=("run_shell",),
        expected_unmodified_files=("other.py",),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E10",
        "Commit all changed files one by one.",
        {
            "a.py": "print('a')\n",
            "b.py": "print('b')\n",
            "c.py": "print('c')\n",
        },
        expected_tools=("git_commit",),
        forbidden_tools=("run_shell",),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E11",
        "Add a comment to main.py. Do not commit anything.",
        {"main.py": "print('hello')\n"},
        expected_tools=("edit_file",),
        forbidden_tools=("git_commit",),
        expected_changed_files=("main.py",),
        efficiency_max_tools=2,
        efficiency_max_turns=3,
    ),
    EvalTask(
        "E12",
        "Create app.py with a hello command.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=(
            "run_shell",
            "git_commit",
        ),
        expected_changed_files=("app.py",),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E13",
        "Add a function to utils.py without changing anything else.",
        {
            "utils.py": ("def existing():\n    return 1\n"),
            "README.md": "# Project\n",
        },
        expected_tools=(
            "read_file",
            "edit_file",
        ),
        forbidden_tools=("git_commit",),
        expected_changed_files=("utils.py",),
        expected_unmodified_files=("README.md",),
        efficiency_max_tools=2,
        efficiency_max_turns=4,
    ),
    EvalTask(
        "E14",
        "Tell me the current Git status.",
        {"main.py": "print('hello')\n"},
        expected_tools=("run_shell",),
        forbidden_tools=(
            "edit_file",
            "git_commit",
        ),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E15",
        "Fix this typo in README.md: 'teh' should become 'the'.",
        {
            "README.md": ("# Title\nThis is teh project.\n"),
        },
        expected_tools=("edit_file",),
        forbidden_tools=(
            "create_files",
            "git_commit",
            "run_shell",
        ),
        expected_changed_files=("README.md",),
        efficiency_max_tools=2,
        efficiency_max_turns=3,
    ),
    EvalTask(
        "E16",
        "Create a simple Python package in mypkg/ with __init__.py and calculator.py.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("git_commit",),
        expected_changed_files=(
            "mypkg/__init__.py",
            "mypkg/calculator.py",
        ),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E17",
        "Read config.py and tell me which setting controls the port.",
        {
            "config.py": ("PORT = 8000\nDEBUG = True\n"),
        },
        expected_tools=("read_file",),
        forbidden_tools=(
            "edit_file",
            "git_commit",
        ),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E18",
        "Create a README.md with a title and one sentence.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("git_commit",),
        expected_changed_files=("README.md",),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E19",
        "Run the tests, and if they fail fix the failure then run them again.",
        {
            "math_utils.py": ("def add(a, b):\n    return a - b\n"),
            "test_math.py": (
                "from math_utils import add\n\ndef test_add():\n    assert add(1, 1) == 2\n"
            ),
        },
        expected_tools=("run_shell",),
        forbidden_tools=("git_commit",),
        efficiency_max_tools=6,
        efficiency_max_turns=8,
    ),
    EvalTask(
        "E20",
        "Read main.py and continue from the current state.",
        {
            "main.py": ("def main():\n    print('resume me')\n"),
        },
        expected_tools=("read_file",),
        forbidden_tools=("git_commit",),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    # --------------------------------------------------------
    # Agentic regression coverage (E21-E30)
    # --------------------------------------------------------
    EvalTask(
        "E21",
        "Update existing settings.py so DEBUG is False. Do not touch README.md.",
        {"settings.py": "DEBUG = True\n", "README.md": "# Keep unchanged\n"},
        expected_tools=("read_file", "edit_file"),
        forbidden_tools=("create_files", "git_commit", "run_shell"),
        expected_changed_files=("settings.py",),
        expected_unmodified_files=("README.md",),
        efficiency_max_tools=2,
        efficiency_max_turns=4,
    ),
    EvalTask(
        "E22",
        "Create a small dashboard/ folder with index.html, styles.css, and app.js.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("run_shell", "git_commit"),
        expected_changed_files=("dashboard/index.html", "dashboard/styles.css", "dashboard/app.js"),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E23",
        "Run the tests. If a test fails, fix the bug and run the tests again until they pass.",
        {
            "calc.py": "def add(a, b):\n    return a - b\n",
            "test_calc.py": "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        },
        expected_tools=("run_shell", "edit_file"),
        forbidden_tools=("git_commit",),
        expected_changed_files=("calc.py",),
        test_command="uv run pytest -q",
        efficiency_max_tools=6,
        efficiency_max_turns=8,
    ),
    EvalTask(
        "E24",
        "Run the test suite twice and report whether both runs pass.",
        {"test_ok.py": "def test_ok():\n    assert True\n"},
        expected_tools=("run_shell",),
        forbidden_tools=("edit_file", "create_files", "git_commit"),
        efficiency_max_tools=2,
        efficiency_max_turns=3,
    ),
    EvalTask(
        "E25",
        "Create a folder called widget and work only inside it. Add index.html and script.js.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("run_shell", "git_commit"),
        expected_changed_files=("widget/index.html", "widget/script.js"),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E26",
        "Create config.json containing exactly {\"enabled\": true}.",
        {},
        expected_tools=("create_files",),
        forbidden_tools=("run_shell", "git_commit"),
        expected_changed_files=("config.json",),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E27",
        "Read api.py, then add a health_check function without changing any other file.",
        {"api.py": "def serve():\n    return 'ok'\n", "notes.txt": "leave me alone\n"},
        expected_tools=("read_file", "edit_file"),
        forbidden_tools=("create_files", "run_shell", "git_commit"),
        expected_changed_files=("api.py",),
        expected_unmodified_files=("notes.txt",),
        efficiency_max_tools=2,
        efficiency_max_turns=4,
    ),
    EvalTask(
        "E28",
        "Verify the existing static frontend and report any missing local assets.",
        {
            "index.html": "<!doctype html><script src='app.js'></script>",
            "app.js": "console.log('ok');\n",
        },
        expected_tools=("verify_frontend",),
        forbidden_tools=("run_shell", "edit_file", "create_files", "git_commit"),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E29",
        "Commit only a.py and b.py, one commit per file, using message 'release widgets'.",
        {"a.py": "print('a')\n", "b.py": "print('b')\n", "other.py": "print('other')\n"},
        expected_tools=("git_commit",),
        forbidden_tools=("run_shell",),
        expected_unmodified_files=("other.py",),
        efficiency_max_tools=1,
        efficiency_max_turns=2,
    ),
    EvalTask(
        "E30",
        "Build a tiny notes app in notes/ with index.html, style.css, and script.js. Keep it static and verify the files.",
        {},
        expected_tools=("create_files", "verify_frontend"),
        forbidden_tools=("run_shell", "git_commit"),
        expected_changed_files=("notes/index.html", "notes/style.css", "notes/script.js"),
        efficiency_max_tools=2,
        efficiency_max_turns=4,
    ),
)
