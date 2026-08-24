def is_commit_request(task: str) -> bool:
    text = task.lower().strip()

    commit_signals = (
        "commit",
        "make a commit",
        "create a commit",
        "git commit",
        "commit changes",
    )

    return any(signal in text for signal in commit_signals)
