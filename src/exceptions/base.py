"""Base exception classes for Clotho."""

from typing import Optional


class ClothoException(Exception):
    """Base exception for all Clotho errors.

    Attributes:
        message: User-friendly message to display
        internal_message: Detailed message for logging (not shown to users)
    """

    def __init__(self, message: str, internal_message: Optional[str] = None):
        self.message = message
        self.internal_message = internal_message or message
        super().__init__(self.message)


class ServiceException(ClothoException):
    """Non-fatal error that can be recovered from.

    The CLI continues running after displaying these errors.
    """
    pass


class SystemException(ClothoException):
    """Fatal error that causes the program to exit.

    Attributes:
        exit_code: Process exit code (default: 1)
    """

    def __init__(
        self,
        message: str,
        internal_message: Optional[str] = None,
        exit_code: int = 1
    ):
        super().__init__(message, internal_message)
        self.exit_code = exit_code
