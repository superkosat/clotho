"""Core WhatsApp ↔ Clotho gateway bridge."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from neonize.aioze.client import NewAClient
from neonize.aioze.events import MessageEv, ConnectedEv, DisconnectedEv

from channels.whatsapp.config import BridgeConfig
from channels.whatsapp.session_map import SessionMap
from cli.api_client import ClothoAPIClient
from cli.ws_client import ClothoWebSocketClient


class WhatsAppBridge:
    """Bridges incoming WhatsApp messages to a running Clotho gateway."""

    def __init__(self, config: BridgeConfig) -> None:
        self.config = config
        self.session_map = SessionMap()
        self.api = ClothoAPIClient(config.host, config.port, config.token)

        db_dir = Path(config.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        self.wa = NewAClient(config.db_path, uuid="clotho-whatsapp")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the bridge. Blocks until disconnected."""
        self.wa.event(ConnectedEv)(self._on_connected)
        self.wa.event(DisconnectedEv)(self._on_disconnect)
        self.wa.event(MessageEv)(self._on_message)
        await self.wa.connect()
        await self.wa.idle()

    async def _on_connected(self, client: NewAClient, event: ConnectedEv) -> None:
        print("[clotho-whatsapp] Connected to WhatsApp.")

    async def _on_disconnect(self, client: NewAClient, event: DisconnectedEv) -> None:
        print("[clotho-whatsapp] Disconnected from WhatsApp.")

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _on_message(self, client: NewAClient, event: MessageEv) -> None:
        # Ignore own messages (echo suppression)
        if event.info.fromMe:
            return

        jid = str(event.info.message_source.chat)
        text = (
            event.Message.conversation
            or event.Message.extendedTextMessage.text
            or ""
        ).strip()

        if not text:
            return

        if not self._is_allowed(jid):
            if self.config.denial_message:
                await client.reply_message(self.config.denial_message, event)
            return

        # Typing indicator (best-effort)
        try:
            await client.send_chat_presence(jid, "composing", "")
        except Exception:
            pass

        try:
            response = await self._run_agent(jid, text)
        except Exception as exc:
            response = f"Sorry, something went wrong: {exc}"

        # Stop typing indicator (best-effort)
        try:
            await client.send_chat_presence(jid, "paused", "")
        except Exception:
            pass

        if not response:
            return

        for chunk in self._chunk(response):
            await client.reply_message(chunk, event)

    # ------------------------------------------------------------------
    # Agent interaction
    # ------------------------------------------------------------------

    async def _run_agent(self, jid: str, text: str) -> str:
        """Send a message to the Clotho gateway and collect the full response."""
        chat_id = self.session_map.get(jid)
        if not chat_id:
            chat_id = self.api.create_chat()
            self.session_map.set(jid, chat_id)

        ws = ClothoWebSocketClient(
            self.config.host, self.config.port, chat_id, self.config.token
        )
        await ws.connect()

        parts: list[str] = []
        done = asyncio.Event()
        error: list[str] = []

        def on_event(data: dict) -> None:
            match data.get("type"):
                case "agent.text_delta":
                    parts.append(data.get("data", {}).get("delta", ""))
                case "agent.text":
                    parts.append(data.get("data", {}).get("text", ""))
                case "agent.tool_request":
                    if self.config.tool_approval == "auto_allow":
                        asyncio.create_task(ws.approve_tools())
                    else:
                        asyncio.create_task(ws.deny_tools())
                case "agent.error":
                    error.append(data.get("data", {}).get("message", "Unknown error"))
                    done.set()
                case "agent.turn_complete":
                    done.set()

        ws.on_message(on_event)
        listen_task = asyncio.create_task(ws.listen())

        try:
            await ws.send_message(text, stream=True)
            await done.wait()
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

    def _is_allowed(self, jid: str) -> bool:
        """Return True if this JID is permitted to use the bot.

        An empty allowlist means all contacts are allowed.
        Allowlist entries are E.164 phone numbers (e.g. +15551234567);
        the JID suffix (@s.whatsapp.net or @g.us) is stripped before comparison.
        """
        if not self.config.allowlist:
            return True
        phone = re.sub(r"@.*$", "", jid)
        normalized_allowlist = [re.sub(r"[^\d]", "", e) for e in self.config.allowlist]
        return phone in normalized_allowlist

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
