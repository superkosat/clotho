"""Gateway-related exceptions."""

from exceptions.base import SystemException


class GatewayStartupError(SystemException):
    """Raised when the gateway fails to start."""

    def __init__(self, reason: str = "unknown"):
        super().__init__(
            message="Failed to start gateway. Check if port 8000 is available.",
            internal_message=f"Gateway startup failed: {reason}",
            exit_code=2
        )


class GatewayConnectionError(SystemException):
    """Raised when unable to connect to the gateway."""

    def __init__(self, host: str, port: int):
        super().__init__(
            message=f"Cannot connect to gateway at {host}:{port}. Is it running?",
            internal_message=f"Connection refused: {host}:{port}",
            exit_code=3
        )


class AuthenticationError(SystemException):
    """Raised for authentication failures."""

    def __init__(self, detail: str = "invalid or missing token"):
        super().__init__(
            message="Authentication failed. Run 'clotho setup' to configure your token.",
            internal_message=f"Auth error: {detail}",
            exit_code=4
        )
