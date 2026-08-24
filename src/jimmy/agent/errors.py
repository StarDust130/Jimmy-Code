from enum import StrEnum


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    PERMISSION = "permission"
    RUNTIME = "runtime"
    UNKNOWN = "unknown"
