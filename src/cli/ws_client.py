"""WebSocket client for real-time agent interaction."""

import asyncio
import json
from typing import Callable

import websockets


class ClothoWebSocketClient:
    """WebSocket client for real-time agent interaction."""

    def __init__(self, host: str, port: int, chat_id: str, token: str):
        """Initialize WebSocket client.

        Args:
            host: Gateway host address
            port: Gateway port number
            chat_id: Chat session ID
            token: Authentication token
        """
        self.url = f"ws://{host}:{port}/ws/{chat_id}?token={token}"
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.message_handler: Callable[[dict], None] | None = None
        self._disconnecting = False

    async def connect(self):
        """Connect to WebSocket."""
        self.ws = await websockets.connect(
            self.url,
            ping_interval=30,
            ping_timeout=120,
            max_size=None,
        )

    async def disconnect(self):
        """Disconnect from WebSocket."""
        if self.ws:
            self._disconnecting = True
            await self.ws.close()

    async def send_message(
        self,
        text: str,
        stream: bool = True,
        content_blocks: list[dict] | None = None,
    ):
        """Send user message to agent.

        Args:
            text: User message text (used alone for plain text messages)
            stream: Whether to request streaming responses
            content_blocks: Optional list of serialized ContentBlock dicts.
                When provided, sent as structured multi-modal content instead
                of a plain text string.

        Raises:
            RuntimeError: If not connected
        """
        if not self.ws:
            raise RuntimeError("Not connected")
        data: dict = {"message": text, "stream": stream}
        if content_blocks:
            data["content"] = content_blocks
        await self.ws.send(json.dumps({
            "type": "run",
            "data": data,
        }))

    async def approve_tools(self):
        """Approve all pending tool executions.

        Raises:
            RuntimeError: If not connected
        """
        if not self.ws:
            raise RuntimeError("Not connected")
        await self.ws.send(json.dumps({
            "type": "tool_approval",
            "data": {"approved": True}
        }))

    async def deny_tools(self):
        """Deny all pending tool executions.

        Raises:
            RuntimeError: If not connected
        """
        if not self.ws:
            raise RuntimeError("Not connected")
        await self.ws.send(json.dumps({
            "type": "tool_approval",
            "data": {"approved": False}
        }))

    async def cancel(self):
        """Cancel current agent run.

        Raises:
            RuntimeError: If not connected
        """
        if not self.ws:
            raise RuntimeError("Not connected")
        await self.ws.send(json.dumps({
            "type": "cancel",
            "data": {}
        }))

    def on_message(self, handler: Callable[[dict], None]):
        """Register message handler.

        Args:
            handler: Callback function for incoming messages
        """
        self.message_handler = handler

    async def listen(self):
        """Listen for messages from server.

        Raises:
            RuntimeError: If not connected
        """
        if not self.ws:
            raise RuntimeError("Not connected")

        try:
            async for message in self.ws:
                data = json.loads(message)
                if self.message_handler:
                    self.message_handler(data)
        except Exception as e:
            # Only notify on unexpected errors, not intentional disconnects
            if not self._disconnecting and self.message_handler:
                self.message_handler({
                    "type": "connection.error",
                    "data": {"message": str(e)}
                })
