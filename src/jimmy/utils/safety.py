import re

DANGEROUS_COMMAND_PATTERNS = [
    r"\brm\s+-rf\s+/",
    r"\bdel\s+/[sq]",
    r"\bformat\s+[a-zA-Z]:",
    r"\bdiskpart\b",
    r"\bshutdown\b",
    r"\breboot\b",
]


def check_shell_command(command: str) -> None:
    """Reject obviously destructive commands."""

    normalized = command.strip().lower()

    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, normalized):
            raise PermissionError(f"Blocked potentially destructive command: {command}")
