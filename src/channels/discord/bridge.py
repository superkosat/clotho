"""Core Discord ↔ Clotho gateway bridge."""

from __future__ import annotations

import asyncio
import sys

import discord

from channels.discord.config import BridgeConfig
from channels.discord.session_map import SessionMap
from cli.api_client import ClothoAPIClient
from cli.ws_client import ClothoWebSocketClient


def _log(msg: str) -> None:
    print(f"[clotho-discord] {msg}", file=sys.stderr, flush=True)


class DiscordBridge:
    """Bridges incoming Discord messages to a running Clotho gateway."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.session_map = SessionMap()
        self.api = ClothoAPIClient(config.host, config.port, config.token)

        intents = discord.Intents.default()
        intents.message_content = True  # required to read message text
        self.client = discord.Client(intents=intents)

        # Register event handlers — assign directly because client.event()
        # uses func.__name__, and our private _on_ready/_on_message names
        # don't match the discord.py event names (on_ready, on_message).
        self.client.on_ready = self._on_ready
        self.client.on_message = self._on_message

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the bridge. Blocks until disconnected."""
        await self.client.start(self.config.bot_token)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_ready(self) -> None:
        print(f"[clotho-discord] Logged in as {self.client.user}")

    async def _on_message(self, message: discord.Message) -> None:
        # Ignore messages from bots (including ourselves)
        if message.author.bot:
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = self.client.user in message.mentions

        # Server messages: check allowlist and mention requirement
        if not is_dm:
            if not self._is_allowed_location(message):
                if self.config.denial_message:
                    await message.reply(self.config.denial_message)
                return
            if self.config.mention_only and not is_mentioned:
                return

        # Extract text, stripping the @mention if present
        text = message.content
        if is_mentioned:
            text = text.replace(f"<@{self.client.user.id}>", "").strip()
        if not text:
            return

        # Check for emergency stop codewords before routing to the agent.
        # These are processed immediately regardless of session state.
        if self.config.stopall_codeword and text.strip() == self.config.stopall_codeword:
            _log("!stopall received — panicking all sessions")
            try:
                affected = await asyncio.to_thread(self.api.panic_all)
                await message.reply(f"Stopped all active sessions ({affected} affected).")
            except Exception as exc:
                _log(f"panic_all failed: {exc}")
                await message.reply("Failed to stop all sessions.")
            return

        if self.config.stop_codeword and text.strip() == self.config.stop_codeword:
            session_key = self._session_key(message)
            chat_id = self.session_map.get(session_key)
            if chat_id:
                _log(f"!stop received — panicking session {chat_id}")
                try:
                    await asyncio.to_thread(self.api.panic_chat, chat_id)
                    await message.reply("Stopped.")
                except Exception as exc:
                    _log(f"panic_chat failed: {exc}")
                    await message.reply("Failed to stop session.")
            else:
                await message.reply("No active session to stop.")
            return

        session_key = self._session_key(message)
        _log(f"Message from {message.author}: {text[:80]!r}")

        async with message.channel.typing():
            try:
                response = await self._run_agent(session_key, text)
            except Exception as exc:
                _log(f"Agent error: {exc}")
                response = f"Sorry, something went wrong: {exc}"

        if not response:
            _log("Empty response from agent, not replying")
            return

        _log(f"Sending response ({len(response)} chars)")
        chunks = self._chunk(response)
        try:
            await message.reply(chunks[0])
            for chunk in chunks[1:]:
                await message.channel.send(chunk)
        except Exception as exc:
            _log(f"Failed to send reply: {exc}")

    # ------------------------------------------------------------------
    # Agent interaction
    # ------------------------------------------------------------------

    async def _run_agent(self, session_key: str, text: str) -> str:
        """Send a message to the Clotho gateway and collect the full response."""
        chat_id = self.session_map.get(session_key)
        if not chat_id:
            _log("Creating new chat session...")
            # Run sync HTTP call in a thread to avoid blocking the event loop
            chat_id = await asyncio.to_thread(self.api.create_chat)
            self.session_map.set(session_key, chat_id)
            _log(f"Created chat {chat_id}")

        ws = ClothoWebSocketClient(
            self.config.host, self.config.port, chat_id, self.config.token
        )
        _log(f"Connecting WebSocket to chat {chat_id}...")
        await ws.connect()
        _log("WebSocket connected")

        parts: list[str] = []
        done = asyncio.Event()
        error: list[str] = []

        def on_event(data: dict) -> None:
            event_type = data.get("type")
            match event_type:
                case "agent.text_delta":
                    parts.append(data.get("data", {}).get("text", ""))
                case "agent.text":
                    parts.append(data.get("data", {}).get("text", ""))
                case "agent.tool_request":
                    if self.config.tool_approval == "auto_allow":
                        asyncio.create_task(ws.approve_tools())
                    else:
                        _log("Auto-denying tool request")
                        asyncio.create_task(ws.deny_tools())
                case "agent.cancelled":
                    _log("Run cancelled")
                    done.set()
                case "agent.error":
                    msg = data.get("data", {}).get("message", "Unknown error")
                    _log(f"Agent error event: {msg}")
                    error.append(msg)
                    done.set()
                case "agent.turn_complete":
                    _log("Turn complete")
                    done.set()
                case _:
                    _log(f"Unhandled event: {event_type}")

        ws.on_message(on_event)
        listen_task = asyncio.create_task(ws.listen())

        try:
            await ws.send_message(text, stream=True)
            _log("Message sent, waiting for response...")
            await asyncio.wait_for(done.wait(), timeout=120)
        except asyncio.TimeoutError:
            _log("Timed out waiting for agent response (120s)")
            error.append("Agent response timed out")
        finally:
            listen_task.cancel()
            try:
                await listen_task
            except (asyncio.CancelledError, Exception):
                pass
            await ws.disconnect()

        if error:
            raise RuntimeError(error[0])

        return "".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _session_key(self, message: discord.Message) -> str:
        if self.config.session_mode == "channel":
            return str(message.channel.id)
        return str(message.author.id)  # default: "user"

    def _is_allowed_location(self, message: discord.Message) -> bool:
        """Return True if this message's guild and channel are permitted.

        Empty list = deny all; ["*"] = allow all; ["id1", ...] = specific IDs.
        """
        guild_list = self.config.allowed_guild_ids
        if not guild_list:
            return False
        if "*" not in guild_list:
            if not message.guild or str(message.guild.id) not in guild_list:
                return False

        channel_list = self.config.allowed_channel_ids
        if not channel_list:
            return False
        if "*" not in channel_list:
            if str(message.channel.id) not in channel_list:
                return False

        return True

    def _chunk(self, text: str) -> list[str]:
        """Split text into chunks no longer than chunk_limit characters.

        Prefers splitting at paragraph boundaries (double newline), then at
        single newlines, then hard-cuts at the limit.
        """
        limit = self.config.chunk_limit
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        remaining = text
        while len(remaining) > limit:
            cut = remaining.rfind("\n\n", 0, limit)
            if cut == -1:
                cut = remaining.rfind("\n", 0, limit)
            if cut == -1:
                cut = limit
            chunks.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()

        if remaining:
            chunks.append(remaining)
        return chunks
