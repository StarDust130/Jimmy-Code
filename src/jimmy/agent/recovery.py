from dataclasses import dataclass

from jimmy.agent.errors import ErrorCategory


@dataclass
class RecoveryDecision:
    should_continue: bool
    retry: bool
    category: ErrorCategory
    message: str


class RecoveryManager:
    """Classifies failures and decides how the agent should continue."""

    def classify(self, error: Exception) -> ErrorCategory:
        if isinstance(error, TimeoutError):
            return ErrorCategory.TIMEOUT

        if isinstance(error, PermissionError):
            return ErrorCategory.PERMISSION

        if isinstance(error, FileNotFoundError):
            return ErrorCategory.NOT_FOUND

        if isinstance(error, (ValueError, TypeError)):
            return ErrorCategory.VALIDATION

        if isinstance(error, RuntimeError):
            return ErrorCategory.RUNTIME

        return ErrorCategory.UNKNOWN

    def recover(self, error: Exception) -> RecoveryDecision:
        category = self.classify(error)

        if category == ErrorCategory.PERMISSION:
            return RecoveryDecision(
                should_continue=True,
                retry=False,
                category=category,
                message=("The action was blocked by permission policy."),
            )

        if category == ErrorCategory.NOT_FOUND:
            return RecoveryDecision(
                should_continue=True,
                retry=False,
                category=category,
                message=(
                    "The requested resource was not found. "
                    "The agent should reconsider the path or search again."
                ),
            )

        if category == ErrorCategory.TIMEOUT:
            return RecoveryDecision(
                should_continue=True,
                retry=True,
                category=category,
                message=("The command timed out. The agent should try a different approach."),
            )

        if category == ErrorCategory.VALIDATION:
            return RecoveryDecision(
                should_continue=True,
                retry=False,
                category=category,
                message=("The tool arguments were invalid. The agent should correct them."),
            )

        return RecoveryDecision(
            should_continue=True,
            retry=False,
            category=category,
            message=(
                f"The tool failed with {type(error).__name__}. "
                "The agent should inspect the error and decide what to do next."
            ),
        )
