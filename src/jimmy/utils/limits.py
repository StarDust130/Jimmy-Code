MAX_TOOL_OUTPUT_CHARS = 12_000


def truncate_output(output: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    """Keep tool output from overwhelming the model context."""

    if len(output) <= limit:
        return output

    truncated = output[:limit]

    return (
        f"{truncated}\n\n"
        f"[Output truncated: {len(output)} characters total. "
        f"Showing first {limit} characters.]"
    )
