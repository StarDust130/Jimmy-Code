from pathlib import Path


def get_workspace() -> Path:
    """Return the current working directory as Jimmy's workspace."""
    workspace = Path.cwd().resolve()

    if not workspace.exists():
        raise RuntimeError("Current workspace does not exist.")

    if not workspace.is_dir():
        raise RuntimeError("Current workspace is not a directory.")

    return workspace
