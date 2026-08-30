from jimmy.agent.errors import ErrorCategory
from jimmy.agent.recovery import RecoveryManager


def test_timeout_is_retryable() -> None:
    manager = RecoveryManager()

    decision = manager.recover(
        TimeoutError(
            "command timed out",
        ),
    )

    assert decision.category == ErrorCategory.TIMEOUT
    assert decision.should_continue is True
    assert decision.retry is True


def test_permission_failure_is_not_retryable() -> None:
    manager = RecoveryManager()

    decision = manager.recover(
        PermissionError(
            "blocked",
        ),
    )

    assert decision.category == ErrorCategory.PERMISSION
    assert decision.should_continue is True
    assert decision.retry is False
    assert "Do not repeat" in decision.message


def test_missing_file_requires_new_strategy() -> None:
    manager = RecoveryManager()

    decision = manager.recover(
        FileNotFoundError(
            "missing",
        ),
    )

    assert decision.category == ErrorCategory.NOT_FOUND
    assert decision.should_continue is True
    assert decision.retry is False
    assert "search" in decision.message.lower()


def test_validation_failure_requires_corrected_arguments() -> None:
    manager = RecoveryManager()

    decision = manager.recover(
        ValueError(
            "invalid arguments",
        ),
    )

    assert decision.category == ErrorCategory.VALIDATION
    assert decision.should_continue is True
    assert decision.retry is False
    assert "arguments" in decision.message.lower()


def test_type_error_is_validation_failure() -> None:
    manager = RecoveryManager()

    decision = manager.recover(
        TypeError(
            "wrong type",
        ),
    )

    assert decision.category == ErrorCategory.VALIDATION
    assert decision.should_continue is True
    assert decision.retry is False


def test_runtime_failure_requires_diagnosis() -> None:
    manager = RecoveryManager()

    decision = manager.recover(
        RuntimeError(
            "pytest: command not found",
        ),
    )

    assert decision.category == ErrorCategory.RUNTIME
    assert decision.should_continue is True
    assert decision.retry is False
    assert "actual error" in decision.message.lower()


def test_unknown_failure_is_not_blindly_retryable() -> None:
    manager = RecoveryManager()

    decision = manager.recover(
        Exception(
            "unexpected failure",
        ),
    )

    assert decision.category == ErrorCategory.UNKNOWN
    assert decision.should_continue is True
    assert decision.retry is False
