from pathlib import Path

from jimmy.exploration.models import ProjectFingerprint

LANGUAGE_MARKERS: dict[str, str] = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".cpp": "C++",
    ".c": "C",
}

FRAMEWORK_MARKERS: dict[str, str] = {
    "pyproject.toml": "Python",
    "package.json": "Node.js",
    "next.config.js": "Next.js",
    "next.config.mjs": "Next.js",
    "vite.config.ts": "Vite",
    "vite.config.js": "Vite",
    "angular.json": "Angular",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
}

PACKAGE_MANAGER_MARKERS: dict[str, str] = {
    "uv.lock": "uv",
    "poetry.lock": "Poetry",
    "package-lock.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "Yarn",
    "bun.lock": "Bun",
}


def detect_languages(root: Path) -> list[str]:
    found: set[str] = set()

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if ".git" in path.parts or ".venv" in path.parts:
            continue

        language = LANGUAGE_MARKERS.get(path.suffix.lower())

        if language:
            found.add(language)

    return sorted(found)


def detect_markers(
    root: Path,
    markers: dict[str, str],
) -> list[str]:
    found: set[str] = set()

    for filename, value in markers.items():
        if (root / filename).exists():
            found.add(value)

    return sorted(found)


def detect_files(
    root: Path,
    names: set[str],
) -> list[str]:
    found: list[str] = []

    for name in names:
        path = root / name

        if path.exists():
            found.append(name)

    return sorted(found)


def build_fingerprint(root: Path) -> ProjectFingerprint:
    config_names = {
        "pyproject.toml",
        "package.json",
        "tsconfig.json",
        "Cargo.toml",
        "go.mod",
        "Dockerfile",
        ".env.example",
    }

    test_dirs = []

    for name in ("tests", "test", "__tests__", "spec"):
        if (root / name).is_dir():
            test_dirs.append(name)

    important_names = {
        "README.md",
        "README",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
    }

    return ProjectFingerprint(
        root=str(root),
        languages=detect_languages(root),
        frameworks=detect_markers(root, FRAMEWORK_MARKERS),
        package_managers=detect_markers(
            root,
            PACKAGE_MANAGER_MARKERS,
        ),
        config_files=detect_files(root, config_names),
        test_directories=sorted(test_dirs),
        important_files=detect_files(
            root,
            important_names,
        ),
    )
