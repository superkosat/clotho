"""Custom exceptions for sandbox operations."""


class SandboxError(Exception):
    """Base exception for sandbox errors."""

    pass


class SandboxNotRunningError(SandboxError):
    """Raised when operation requires running sandbox."""

    pass


class SandboxTimeoutError(SandboxError):
    """Raised when command execution times out."""

    def __init__(self, timeout: int):
        super().__init__(f"Command timed out after {timeout} seconds")
        self.timeout = timeout


class SandboxResourceError(SandboxError):
    """Raised when resource limits are exceeded (OOM, etc)."""

    pass


class SandboxImageNotFoundError(SandboxError):
    """Raised when sandbox Docker image not found."""

    def __init__(self):
        super().__init__(
            "Sandbox image 'clotho-sandbox:latest' not found. "
            "Run: python -m sandbox.build_image"
        )


class SandboxDockerError(SandboxError):
    """Raised when Docker daemon is unavailable."""

    def __init__(self):
        super().__init__(
            "Docker daemon not available. "
            "Install Docker Desktop (Windows/Mac) or start dockerd service (Linux)"
        )


class WorkspaceAccessError(SandboxError):
    """Raised when attempting to access paths outside workspace."""

    def __init__(self, path: str):
        super().__init__(
            f"Access denied: {path} is outside workspace. "
            f"Only /workspace and /tmp are accessible."
        )
        self.path = path
