"""Typed, sanitized failures raised by generation worker database adapters."""


class WorkerRepositoryError(RuntimeError):
    """Database adapter failure with an explicit safe retry policy."""

    def __init__(self, error_code: str, *, retryable: bool = True):
        self.error_code = error_code
        self.retryable = retryable
        super().__init__(error_code)
