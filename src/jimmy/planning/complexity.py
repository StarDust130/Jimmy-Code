from jimmy.planning.models import TaskComplexity

COMPLEX_SIGNALS = (
    "refactor",
    "migrate",
    "migration",
    "architecture",
    "redesign",
    "implement feature",
    "multiple",
    "across the project",
    "investigate",
    "debug",
    "performance",
    "concurrency",
    "race condition",
    "integration",
)


def classify_task(task: str) -> TaskComplexity:
    """
    Cheap deterministic gate used to decide whether
    a dedicated planning call is worth the cost.
    """

    normalized = task.strip().lower()

    if len(normalized) > 180:
        return TaskComplexity.COMPLEX

    matched_signals = sum(signal in normalized for signal in COMPLEX_SIGNALS)

    if matched_signals >= 1:
        return TaskComplexity.COMPLEX

    return TaskComplexity.SIMPLE
