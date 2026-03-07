"""Agent-related exceptions."""

from exceptions.base import ServiceException


class NoModelConfiguredError(ServiceException):
    """Raised when invoking the agent without a model configured."""

    def __init__(self):
        super().__init__(
            message="No model selected. Add a default profile or set an active profile with /profile use <name>",
            internal_message="ClothoController.model is None"
        )


class NoActiveChatError(ServiceException):
    """Raised when performing chat operations without an active chat."""

    def __init__(self):
        super().__init__(
            message="No active chat session. Start a new chat first.",
            internal_message="ClothoController.context is None"
        )


class ProviderNotSupportedError(ServiceException):
    """Raised when an unsupported model provider is requested."""

    def __init__(self, provider: str):
        super().__init__(
            message=f"Provider '{provider}' is not supported. Use: ollama, openai, or anthropic",
            internal_message=f"Unknown provider: {provider}"
        )


class ToolExecutionError(ServiceException):
    """Raised when a tool fails during execution."""

    def __init__(self, tool_name: str, reason: str):
        super().__init__(
            message=f"Tool '{tool_name}' failed: {reason}",
            internal_message=f"Tool execution error in {tool_name}: {reason}"
        )
