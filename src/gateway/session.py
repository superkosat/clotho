import asyncio
import logging
import threading
from uuid import UUID
from pathlib import Path

logger = logging.getLogger(__name__)

from agent.core import ClothoController
from agent.models.model_registry import lookup_model
from agent.tools.schemas.bash import bash_tool
from agent.tools.schemas.read import read_tool
from agent.tools.schemas.write import write_tool
from agent.tools.schemas.edit import edit_tool
from gateway.dispatcher import EventDispatcher
from gateway.services.profile_service import ProfileService
from mcp_client import MCPManager

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
        self.dispatcher = EventDispatcher()
        # Start the consumer if there's a running event loop (async context).
        # Sync callers (e.g. REST POST /api/chats) don't have one — the
        # dispatcher is started lazily when the first WebSocket connects or
        # the scheduler submits an event.
        try:
            asyncio.get_running_loop()
            self.dispatcher.start()
        except RuntimeError:
            pass
        self.cancel_event = asyncio.Event()
        self.pending_approval: asyncio.Future | None = None
        self.current_profile_name = current_profile_name


class SessionManager:
    """Maps chat IDs to in-memory SessionState instances."""

    def __init__(self, mcp_manager: MCPManager | None = None):
        self._sessions: dict[UUID, SessionState] = {}
        self._lock = threading.Lock()
        self._mcp_manager = mcp_manager

    def _all_tools(self) -> list:
        tools = list(DEFAULT_TOOLS)
        if self._mcp_manager:
            tools.extend(self._mcp_manager.get_tools())
        return tools

    def create_session(self) -> tuple[UUID, SessionState]:
        controller = ClothoController()
        controller.register_tools(self._all_tools())
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
        with self._lock:
            if chat_id in self._sessions:
                return self._sessions[chat_id]

        controller = ClothoController()
        controller.register_tools(self._all_tools())
        profile_name = self._set_default_model(controller)
        if not controller.load_chat(chat_id):
            raise ValueError(f"Chat {chat_id} not found")
        state = SessionState(controller, current_profile_name=profile_name)

        with self._lock:
            if chat_id not in self._sessions:
                self._sessions[chat_id] = state
            return self._sessions[chat_id]

    @staticmethod
    def _resolve_limits(profile) -> tuple[int | None, int | None]:
        """Return (context_window, max_output_tokens) for a profile.

        Profile values take precedence; registry fills in any that are None.
        """
        registry = lookup_model(profile.model) or {}
        context_window = profile.context_window or registry.get("context_window")
        max_output_tokens = profile.max_output_tokens or registry.get("max_output_tokens")
        return context_window, max_output_tokens

    def _set_default_model(self, controller: ClothoController) -> str | None:
        try:
            default_name = ProfileService.get_default()
            if default_name:
                profile = ProfileService.get_profile(default_name)
                context_window, max_output_tokens = self._resolve_limits(profile)
                controller.set_model(
                    provider=profile.provider,
                    model=profile.model,
                    base_url=profile.base_url,
                    api_key=profile.api_key,
                    context_window=context_window,
                    max_output_tokens=max_output_tokens,
                )
                return default_name
        except Exception as e:
            logger.warning("Failed to load default model: %s", e)
        return None

    def remove_session(self, chat_id: UUID):
        state = self._sessions.get(chat_id)
        if state:
            state.dispatcher.stop()
            state.controller._cleanup_sandbox()
        self._sessions.pop(chat_id, None)

    def panic_all(self) -> int:
        with self._lock:
            sessions = list(self._sessions.values())
        for state in sessions:
            state.cancel_event.set()
            if state.pending_approval and not state.pending_approval.done():
                state.pending_approval.set_result({"approved": False})
            state.dispatcher.cancel_current()
            state.dispatcher.drain()
        return len(sessions)

    def switch_profile(self, chat_id: UUID, profile_name: str) -> None:
        state = self.get_or_load_session(chat_id)
        profile = ProfileService.get_profile(profile_name)
        context_window, max_output_tokens = self._resolve_limits(profile)

        # Guard: refuse switch if current context would exceed the new model's window
        if context_window:
            current_tokens = (
                state.controller._last_input_tokens
                or state.controller._estimate_tokens_heuristic()
            )
            if current_tokens > context_window:
                raise ValueError(
                    f"Current context (~{current_tokens:,} tokens) exceeds "
                    f"'{profile_name}' context window ({context_window:,} tokens). "
                    f"Run /compact first, or stay on the current model."
                )

        state.controller.set_model(
            provider=profile.provider,
            model=profile.model,
            base_url=profile.base_url,
            api_key=profile.api_key,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
        )
        state.current_profile_name = profile_name

    def get_active_profile(self, chat_id: UUID) -> str | None:
        state = self.get_or_load_session(chat_id)
        return state.current_profile_name

    def list_chats(self) -> list[str]:
        projects_dir = Path.home() / ".clotho" / "projects"
        if not projects_dir.exists():
            return []
        return [f.stem for f in projects_dir.glob("*.jsonl")]

    @property
    def active_count(self) -> int:
        return len(self._sessions)
