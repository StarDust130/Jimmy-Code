from jimmy.agent.errors import ErrorCategory
from jimmy.agent.recovery import RecoveryManager


def test_timeout_is_retryable() -> None:
    manager = RecoveryManager()

    decision = manager.recover(TimeoutError("command timed out"))

    assert decision.category == ErrorCategory.TIMEOUT
    assert decision.should_continue is True
    assert decision.retry is True


def test_permission_failure_is_not_retryable() -> None:
    manager = RecoveryManager()

    decision = manager.recover(PermissionError("blocked"))

    assert decision.category == ErrorCategory.PERMISSION
    assert decision.should_continue is True
    assert decision.retry is False


def test_missing_file_requires_new_strategy() -> None:
    manager = RecoveryManager()

    decision = manager.recover(FileNotFoundError("missing"))

    assert decision.category == ErrorCategory.NOT_FOUND
    assert decision.retry is False
    assert decision.should_continue is True
