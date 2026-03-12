import asyncio
import logging
import threading
from uuid import UUID
from pathlib import Path

logger = logging.getLogger(__name__)

from agent.core import ClothoController
from agent.tools.schemas.bash import bash_tool
from agent.tools.schemas.read import read_tool
from agent.tools.schemas.write import write_tool
from agent.tools.schemas.edit import edit_tool
from gateway.services.profile_service import ProfileService

DEFAULT_TOOLS = [
    bash_tool,
    read_tool,
    write_tool,
    edit_tool,
]

class SessionState:
    """Wraps a ClothoController with concurrency primitives for WebSocket runs."""

    def __init__(self, controller: ClothoController, current_profile_name: str | None = None):
        self.controller = controller
        self.run_lock = asyncio.Lock()
        self.cancel_event = asyncio.Event()
        self.pending_approval: asyncio.Future | None = None
        self.current_profile_name = current_profile_name  # Track active profile


class SessionManager:
    """Maps chat IDs to in-memory SessionState instances."""

    def __init__(self):
        self._sessions: dict[UUID, SessionState] = {}
        self._lock = threading.Lock()

    def create_session(self) -> tuple[UUID, SessionState]:
        controller = ClothoController()
        controller.register_tools(DEFAULT_TOOLS)
        profile_name = self._set_default_model(controller)
        controller.new_chat()
        chat_id = controller.current_project_id
        state = SessionState(controller, current_profile_name=profile_name)
        with self._lock:
            self._sessions[chat_id] = state
        return chat_id, state

    def get_session(self, chat_id: UUID) -> SessionState | None:
        return self._sessions.get(chat_id)

    def get_or_load_session(self, chat_id: UUID) -> SessionState:
        """Get existing session or hydrate from disk (thread-safe)."""
        with self._lock:
            if chat_id in self._sessions:
                return self._sessions[chat_id]

        # Load outside lock (slow I/O), then check again
        controller = ClothoController()
        controller.register_tools(DEFAULT_TOOLS)
        profile_name = self._set_default_model(controller)
        if not controller.load_chat(chat_id):
            raise ValueError(f"Chat {chat_id} not found")
        state = SessionState(controller, current_profile_name=profile_name)

        with self._lock:
            # Another thread may have loaded it while we were working
            if chat_id not in self._sessions:
                self._sessions[chat_id] = state
            return self._sessions[chat_id]

    def _set_default_model(self, controller: ClothoController) -> str | None:
        """Load and apply default model profile if available.

        Returns:
            The name of the profile that was applied, or None if no profile was set.
        """
        try:
            default_name = ProfileService.get_default()
            if default_name:
                profile = ProfileService.get_profile(default_name)
                controller.set_model(
                    provider=profile.provider,
                    model=profile.model,
                    base_url=profile.base_url,
                    api_key=profile.api_key,
                )
                return default_name
        except Exception as e:
            logger.warning("Failed to load default model: %s", e)
        return None

    def remove_session(self, chat_id: UUID):
        state = self._sessions.get(chat_id)
        if state:
            state.controller._cleanup_sandbox()  # Cleanup sandbox
        self._sessions.pop(chat_id, None)

    def switch_profile(self, chat_id: UUID, profile_name: str) -> None:
        """Switch the active model profile for a session.

        Args:
            chat_id: The session ID
            profile_name: The name of the profile to switch to

        Raises:
            ValueError: If session not found or profile doesn't exist
        """
        state = self.get_or_load_session(chat_id)

        # Get the profile and apply it
        profile = ProfileService.get_profile(profile_name)
        state.controller.set_model(
            provider=profile.provider,
            model=profile.model,
            base_url=profile.base_url,
            api_key=profile.api_key,
        )
        state.current_profile_name = profile_name

    def get_active_profile(self, chat_id: UUID) -> str | None:
        """Get the name of the currently active profile for a session.

        Args:
            chat_id: The session ID

        Returns:
            The name of the active profile, or None if no profile is set

        Raises:
            ValueError: If session not found
        """
        state = self.get_or_load_session(chat_id)
        return state.current_profile_name

    def list_chats(self) -> list[str]:
        """List all chat IDs from disk."""
        projects_dir = Path.home() / ".clotho" / "projects"
        if not projects_dir.exists():
            return []
        return [f.stem for f in projects_dir.glob("*.jsonl")]

    @property
    def active_count(self) -> int:
        return len(self._sessions)
