from __future__ import annotations

from dataclasses import dataclass

from jimmy.agent.errors import ErrorCategory


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    should_continue: bool
    retry: bool
    category: ErrorCategory
    message: str


class RecoveryManager:
    """
    Classifies a real execution failure and gives the agent
    useful next-step guidance.

    RecoveryManager does not choose tools and does not execute
    anything. The LLM decides the next action.
    """

    def classify(
        self,
        error: Exception,
    ) -> ErrorCategory:
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

    def recover(
        self,
        error: Exception,
    ) -> RecoveryDecision:
        category = self.classify(error)
        error_text = str(error).strip()

        if category == ErrorCategory.PERMISSION:
            return RecoveryDecision(
                should_continue=True,
                retry=False,
                category=category,
                message=(
                    "Permission was denied. "
                    "Do not repeat the same action. "
                    "Choose an allowed approach or ask the user."
                ),
            )

        if category == ErrorCategory.NOT_FOUND:
            return RecoveryDecision(
                should_continue=True,
                retry=False,
                category=category,
                message=(
                    "The requested resource was not found. "
                    "Do not retry the same path blindly. "
                    "Inspect the workspace or search for the correct path."
                ),
            )

        if category == ErrorCategory.VALIDATION:
            return RecoveryDecision(
                should_continue=True,
                retry=False,
                category=category,
                message=(
                    "The tool arguments were invalid. "
                    "Use the actual validation error to correct the arguments "
                    "before trying again."
                ),
            )

        if category == ErrorCategory.TIMEOUT:
            return RecoveryDecision(
                should_continue=True,
                retry=True,
                category=category,
                message=(
                    "The operation timed out. "
                    "Do not blindly repeat it. "
                    "Retry only when the operation is still appropriate, "
                    "or use a smaller/faster approach."
                ),
            )

        if category == ErrorCategory.RUNTIME:
            detail = f" Actual error: {error_text}" if error_text else ""

            return RecoveryDecision(
                should_continue=True,
                retry=False,
                category=category,
                message=(
                    "The operation failed at runtime."
                    f"{detail} "
                    "Inspect the actual failure and choose the next "
                    "action based on that evidence. "
                    "Do not blindly repeat the same action."
                ),
            )

        detail = f" Actual error: {error_text}" if error_text else ""

        return RecoveryDecision(
            should_continue=True,
            retry=False,
            category=category,
            message=(
                "An unexpected operation failure occurred."
                f"{detail} "
                "Inspect the actual error and choose the next "
                "useful action."
            ),
        )
