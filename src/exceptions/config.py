"""Configuration-related exceptions."""

from exceptions.base import ServiceException, SystemException


class ProfileNotFoundError(ServiceException):
    """Raised when a requested profile doesn't exist."""

    def __init__(self, profile_name: str):
        super().__init__(
            message=f"Profile '{profile_name}' not found. Use /profiles to list available profiles.",
            internal_message=f"Profile lookup failed: {profile_name}"
        )


class ConfigurationError(SystemException):
    """Raised for critical configuration issues."""

    def __init__(self, detail: str):
        super().__init__(
            message=f"Configuration error: {detail}",
            internal_message=f"Config error: {detail}",
            exit_code=5
        )


class ValidationError(ServiceException):
    """Raised when request validation fails."""

    def __init__(self, detail: str):
        super().__init__(
            message=detail,
            internal_message=f"Validation error: {detail}"
        )
