"""REST client for Clotho gateway API."""

import requests

import exceptions


# Map exception class names to classes for reconstruction
EXCEPTION_MAP = {cls.__name__: cls for cls in [
    exceptions.NoModelConfiguredError,
    exceptions.NoActiveChatError,
    exceptions.ProviderNotSupportedError,
    exceptions.ToolExecutionError,
    exceptions.GatewayStartupError,
    exceptions.GatewayConnectionError,
    exceptions.AuthenticationError,
    exceptions.ProfileNotFoundError,
    exceptions.ConfigurationError,
    exceptions.ValidationError,
]}


def _handle_response(response: requests.Response) -> None:
    """Check response and raise appropriate exception if error."""
    if response.ok:
        return

    try:
        data = response.json()
    except ValueError:
        # Response isn't JSON, fall back to HTTP error
        response.raise_for_status()
        return

    # FastAPI HTTPException wraps error in 'detail'
    detail = data.get("detail", data)
    if isinstance(detail, dict):
        error_type = detail.get("error")
        message = detail.get("message", "Unknown error")
    else:
        error_type = data.get("error")
        message = data.get("message", str(detail) if detail else "Unknown error")

    if error_type in EXCEPTION_MAP:
        exc_class = EXCEPTION_MAP[error_type]
        # Create exception with just message (bypass __init__ params)
        exc = exceptions.ServiceException.__new__(exc_class)
        exc.message = message
        exc.internal_message = message
        exc.args = (message,)  # Required for Exception.__str__
        raise exc

    # Raise with the human-readable message extracted from the response body
    raise exceptions.ServiceException(message=message)


class ClothoAPIClient:
    """REST client for Clotho gateway."""

    def __init__(self, host: str, port: int, token: str):
        """Initialize API client.

        Args:
            host: Gateway host address
            port: Gateway port number
            token: Authentication token
        """
        self.base_url = f"http://{host}:{port}"
        self.headers = {"Authorization": f"Bearer {token}"}

    # Chat endpoints

    def create_chat(self) -> str:
        """Create new chat session.

        Returns:
            Chat ID as string
        """
        response = requests.post(
            f"{self.base_url}/api/chats",
            headers=self.headers
        )
        _handle_response(response)
        return response.json()["chat_id"]

    def list_chats(self) -> list[dict]:
        """List all chat sessions.

        Returns:
            List of chat dictionaries with chat_id
        """
        response = requests.get(
            f"{self.base_url}/api/chats",
            headers=self.headers
        )
        _handle_response(response)
        return response.json()["chats"]

    def delete_chat(self, chat_id: str) -> None:
        """Delete chat session.

        Args:
            chat_id: Chat ID to delete
        """
        response = requests.delete(
            f"{self.base_url}/api/chats/{chat_id}",
            headers=self.headers
        )
        _handle_response(response)

    # Profile endpoints

    def list_profiles(self) -> dict:
        """List all model profiles.

        Returns:
            Dictionary with 'default' (str | None) and 'profiles' (dict)
        """
        response = requests.get(
            f"{self.base_url}/api/profiles",
            headers=self.headers
        )
        _handle_response(response)
        return response.json()

    def create_profile(self, name: str, profile: dict) -> None:
        """Create new model profile.

        Args:
            name: Profile name
            profile: Profile data (provider, model, base_url, api_key)
        """
        response = requests.post(
            f"{self.base_url}/api/profiles",
            headers=self.headers,
            json={"name": name, "profile": profile}
        )
        _handle_response(response)

    def delete_profile(self, name: str) -> None:
        """Delete model profile.

        Args:
            name: Profile name to delete
        """
        response = requests.delete(
            f"{self.base_url}/api/profiles/{name}",
            headers=self.headers
        )
        _handle_response(response)

    def get_default_profile(self) -> str | None:
        """Get default profile name.

        Returns:
            Default profile name or None
        """
        response = requests.get(
            f"{self.base_url}/api/profiles/default/current",
            headers=self.headers
        )
        _handle_response(response)
        return response.json().get("profile_name")

    def set_default_profile(self, name: str) -> None:
        """Set default profile.

        Args:
            name: Profile name to set as default
        """
        response = requests.post(
            f"{self.base_url}/api/profiles/default/set",
            headers=self.headers,
            json={"profile_name": name}
        )
        _handle_response(response)

    def get_active_profile(self, chat_id: str) -> str | None:
        """Get active profile for chat.

        Args:
            chat_id: Chat ID

        Returns:
            Active profile name or None
        """
        response = requests.get(
            f"{self.base_url}/api/chats/{chat_id}/active-profile",
            headers=self.headers
        )
        _handle_response(response)
        return response.json().get("profile_name")

    def set_active_profile(self, chat_id: str, profile_name: str) -> None:
        """Set active profile for chat.

        Args:
            chat_id: Chat ID
            profile_name: Profile name to activate
        """
        response = requests.post(
            f"{self.base_url}/api/chats/{chat_id}/active-profile",
            headers=self.headers,
            json={"profile_name": profile_name}
        )
        _handle_response(response)

    # Permission endpoints

    def get_permissions(self) -> dict:
        """Get current permission config.

        Returns:
            Dictionary with 'mode' and 'tool_overrides'
        """
        response = requests.get(
            f"{self.base_url}/api/permissions",
            headers=self.headers
        )
        _handle_response(response)
        return response.json()

    def update_permissions(self, mode: str, tool_overrides: dict) -> None:
        """Update permissions.

        Args:
            mode: Permission mode (interactive/autonomous/readonly)
            tool_overrides: Dictionary of tool name to permission level
        """
        response = requests.put(
            f"{self.base_url}/api/permissions",
            headers=self.headers,
            json={"mode": mode, "tool_overrides": tool_overrides}
        )
        _handle_response(response)

    # Sandbox endpoints

    def get_sandbox(self) -> bool:
        """Get current sandbox enabled state."""
        response = requests.get(
            f"{self.base_url}/api/sandbox",
            headers=self.headers
        )
        _handle_response(response)
        return response.json()["enabled"]

    def set_sandbox(self, enabled: bool) -> None:
        """Enable or disable the sandbox."""
        response = requests.post(
            f"{self.base_url}/api/sandbox",
            headers=self.headers,
            json={"enabled": enabled}
        )
        _handle_response(response)

    def build_sandbox(self) -> None:
        """Build the sandbox Docker image."""
        response = requests.post(
            f"{self.base_url}/api/sandbox/build",
            headers=self.headers,
        )
        _handle_response(response)

    # Control endpoints

    def compact_chat(self, chat_id: str) -> dict:
        """Trigger manual context compaction for a chat."""
        response = requests.post(
            f"{self.base_url}/api/chats/{chat_id}/compact",
            headers=self.headers,
        )
        _handle_response(response)
        return response.json()

    def panic_chat(self, chat_id: str) -> None:
        """Cancel the active run and drain queued work for a session."""
        response = requests.post(
            f"{self.base_url}/api/chats/{chat_id}/panic",
            headers=self.headers,
        )
        _handle_response(response)

    def panic_all(self) -> int:
        """Cancel all active sessions and drain their queues. Returns sessions affected."""
        response = requests.post(
            f"{self.base_url}/api/panic",
            headers=self.headers,
        )
        _handle_response(response)
        return response.json().get("sessions_affected", 0)

    def get_available_tools(self) -> list[str]:
        """Get list of available tool names.

        Returns:
            List of valid tool names
        """
        response = requests.get(
            f"{self.base_url}/api/permissions/tools",
            headers=self.headers
        )
        _handle_response(response)
        return response.json()["tools"]
