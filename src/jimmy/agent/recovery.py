from dataclasses import dataclass


@dataclass
class RecoveryDecision:
    should_continue: bool
    message: str


class RecoveryManager:
    """Handles failures encountered during agent execution."""

    def recover(self, error: Exception) -> RecoveryDecision:
        return RecoveryDecision(
            should_continue=True,
            message=(f"An error occurred: {type(error).__name__}: {error}"),
        )
