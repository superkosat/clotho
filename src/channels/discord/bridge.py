"""Core Discord ↔ Clotho gateway bridge."""

from __future__ import annotations

import asyncio
import base64
import re
import sys
import tempfile
from pathlib import Path

import discord

from channels.discord.config import BridgeConfig
from channels.discord.session_map import SessionMap
from cli.api_client import ClothoAPIClient
from cli.ws_client import ClothoWebSocketClient
from scheduler.job import DeliveryTarget
from scheduler.scheduler import ClothoScheduler, register_delivery_handler


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

        # Scheduler — shares the event loop with the Discord client.
        # Uses the bridge's own sessions file so scheduled jobs run in the
        # same chat sessions as interactive messages for a given channel/user.
        self._scheduler = ClothoScheduler(
            gateway_host=config.host,
            gateway_port=config.port,
            gateway_token=config.token,
            sessions_path=str(self.session_map._path),
        )
        # Register this bridge's Discord client as the delivery backend.
        # Other bridges register their own handlers for their channel types.
        register_delivery_handler("discord_channel", self._deliver_to_channel)
        register_delivery_handler("discord_dm", self._deliver_dm)

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
        count = self._scheduler.load_jobs()
        self._scheduler.start()
        if count:
            _log(f"Scheduler started with {count} job(s)")

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
        if not text and not message.attachments:
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

        # Process attachments into content blocks.
        # When attachments are present, the user's text and all attachment
        # blocks are combined into a single multi-modal content list so the
        # controller builds one UserTurn containing everything.
        content_blocks = await self._process_attachments(message.attachments)
        if content_blocks:
            # Prepend the user's text (if any) so the model sees it alongside attachments
            if text:
                content_blocks.insert(0, {"type": "text", "text": text})

        async with message.channel.typing():
            try:
                response = await self._run_agent(
                    session_key, text, message.channel,
                    content_blocks=content_blocks or None,
                )
            except Exception as exc:
                _log(f"Agent error: {exc}")
                response = f"Sorry, something went wrong: {exc}"

        if not response:
            _log("Empty response from agent, not replying")
            return

        # Extract reaction directives ({{react:emoji}}) before sending text
        response, reactions = self._extract_reactions(response)

        _log(f"Sending response ({len(response)} chars)")
        chunks = self._chunk(response)
        try:
            await message.reply(chunks[0])
            for chunk in chunks[1:]:
                await message.channel.send(chunk)
        except Exception as exc:
            _log(f"Failed to send reply: {exc}")

        # Apply agent-requested reactions to the user's original message
        for emoji in reactions:
            try:
                await message.add_reaction(emoji)
            except Exception as exc:
                _log(f"Failed to add reaction {emoji!r}: {exc}")

    # ------------------------------------------------------------------
    # Agent interaction
    # ------------------------------------------------------------------

    async def _run_agent(
        self,
        session_key: str,
        text: str,
        channel: discord.abc.Messageable | None = None,
        content_blocks: list[dict] | None = None,
    ) -> str:
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
                    calls = data.get("data", {}).get("tool_calls", [])
                    names = [tc.get("name", "?") for tc in calls]
                    _log(f"Tool approval requested: {names}")
                    if self.config.tool_approval == "auto_allow":
                        asyncio.create_task(ws.approve_tools())
                    else:
                        _log("Auto-denying tool request")
                        asyncio.create_task(ws.deny_tools())
                case "agent.tool_denied":
                    reason = data.get("data", {}).get("reason", "")
                    _log(f"Tool denied by policy: {reason}")
                case "agent.tool_use_start":
                    d = data.get("data", {})
                    _log(f"Tool call: {d.get('tool_call_name', '?')}()")
                case "agent.tool_result":
                    d = data.get("data", {})
                    name = d.get("tool_name", "?")
                    is_err = d.get("is_error", False)
                    content = d.get("content", "")
                    preview = content[:200] + "…" if len(content) > 200 else content
                    status = "ERROR" if is_err else "ok"
                    _log(f"Tool result [{name}] ({status}): {preview}")
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
                case "agent.context_compacted":
                    turns = data.get("data", {}).get("turns_removed", 0)
                    _log(f"Context compacted ({turns} turns removed)")
                    if channel is not None:
                        asyncio.create_task(
                            channel.send(
                                f"_Compacting context ({turns} turns removed) — still working…_"
                            )
                        )
                case _:
                    _log(f"Unhandled event: {event_type}")

        ws.on_message(on_event)
        listen_task = asyncio.create_task(ws.listen())

        try:
            await ws.send_message(text, stream=True, content_blocks=content_blocks)
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
    # Attachment processing
    # ------------------------------------------------------------------

    _IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    _AUDIO_EXTENSIONS = {".ogg", ".mp3", ".wav", ".m4a", ".flac"}
    _TEXT_EXTENSIONS = {
        ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml",
        ".py", ".js", ".ts", ".html", ".css", ".sh", ".toml", ".ini",
        ".c", ".cpp", ".h", ".java", ".go", ".rs", ".rb", ".php",
    }
    _MAX_TEXT_SIZE = 100_000  # 100 KB — skip very large text files

    async def _process_attachments(
        self, attachments: list[discord.Attachment]
    ) -> list[dict]:
        """Download Discord attachments and convert to content block dicts."""
        blocks: list[dict] = []
        for att in attachments:
            ext = Path(att.filename).suffix.lower()
            try:
                if ext in self._IMAGE_EXTENSIONS:
                    data = await att.read()
                    b64 = base64.b64encode(data).decode()
                    media_type = att.content_type or f"image/{ext.lstrip('.')}"
                    blocks.append({
                        "type": "image",
                        "source_type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    })
                    _log(f"Attached image: {att.filename} ({len(data)} bytes)")

                elif ext in self._AUDIO_EXTENSIONS:
                    # Save to temp file — agent can transcribe via whisper-transcribe skill
                    tmp = Path(tempfile.gettempdir()) / f"clotho_{att.filename}"
                    data = await att.read()
                    tmp.write_bytes(data)
                    blocks.append({
                        "type": "text",
                        "text": (
                            f"[Audio message received: {att.filename} "
                            f"({len(data)} bytes), saved to: {tmp}. "
                            f"Use the whisper-transcribe skill to transcribe this file, "
                            f"then respond to what the user said. "
                            f"Do NOT repeat the transcription — reply conversationally.]"
                        ),
                    })
                    _log(f"Attached audio: {att.filename} → {tmp}")

                elif ext in self._TEXT_EXTENSIONS and att.size <= self._MAX_TEXT_SIZE:
                    data = await att.read()
                    text_content = data.decode("utf-8", errors="replace")
                    blocks.append({
                        "type": "text",
                        "text": (
                            f"[Attached file: {att.filename}]\n"
                            f"```\n{text_content}\n```"
                        ),
                    })
                    _log(f"Attached text file: {att.filename} ({len(data)} bytes)")

                else:
                    blocks.append({
                        "type": "text",
                        "text": (
                            f"[Attached file: {att.filename} "
                            f"({att.content_type or 'unknown type'}, {att.size} bytes) "
                            f"— binary file, contents not included]"
                        ),
                    })
                    _log(f"Attached binary file (noted): {att.filename}")

            except Exception as exc:
                _log(f"Failed to process attachment {att.filename}: {exc}")
                blocks.append({
                    "type": "text",
                    "text": f"[Failed to process attachment: {att.filename} — {exc}]",
                })

        return blocks

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    _REACT_PATTERN = re.compile(r"\{\{react:([^}]+)\}\}")

    def _extract_reactions(self, text: str) -> tuple[str, list[str]]:
        """Strip {{react:emoji}} directives from text, return cleaned text and emoji list."""
        reactions = self._REACT_PATTERN.findall(text)
        cleaned = self._REACT_PATTERN.sub("", text).strip()
        return cleaned, reactions

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

    # ------------------------------------------------------------------
    # Scheduled job delivery
    # ------------------------------------------------------------------

    async def _deliver_to_channel(self, target: DeliveryTarget, content: str) -> None:
        """Deliver a job response to a Discord channel."""
        channel_id = int(target.params["channel_id"])
        channel = self.client.get_channel(channel_id) or await self.client.fetch_channel(channel_id)
        for chunk in self._chunk(content):
            await channel.send(chunk)

    async def _deliver_dm(self, target: DeliveryTarget, content: str) -> None:
        """Deliver a job response as a Discord DM to a user."""
        user_id = int(target.params["user_id"])
        user = await self.client.fetch_user(user_id)
        dm = await user.create_dm()
        for chunk in self._chunk(content):
            await dm.send(chunk)
