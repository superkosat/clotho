"""Shared exceptions for Clotho.

Two categories:
- ServiceException: Non-fatal, recoverable errors with user-friendly messages
- SystemException: Fatal errors that should terminate the program
"""

from exceptions.base import ClothoException, ServiceException, SystemException
from exceptions.agent import (
    NoModelConfiguredError,
    NoActiveChatError,
    ProviderNotSupportedError,
    ToolExecutionError,
)
from exceptions.gateway import (
    GatewayStartupError,
    GatewayConnectionError,
    AuthenticationError,
)
from exceptions.config import (
    ProfileNotFoundError,
    ConfigurationError,
    ValidationError,
)

__all__ = [
    # Base
    "ClothoException",
    "ServiceException",
    "SystemException",
    # Agent
    "NoModelConfiguredError",
    "NoActiveChatError",
    "ProviderNotSupportedError",
    "ToolExecutionError",
    # Gateway
    "GatewayStartupError",
    "GatewayConnectionError",
    "AuthenticationError",
    # Config
    "ProfileNotFoundError",
    "ConfigurationError",
    "ValidationError",
]
