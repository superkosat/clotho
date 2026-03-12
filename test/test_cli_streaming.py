"""Tests for CLI streaming toggle and WebSocket client stream flag."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cli.ws_client import ClothoWebSocketClient


# ---------------------------------------------------------------------------
# WebSocket client send_message stream flag
# ---------------------------------------------------------------------------

class TestWebSocketClientStream:
    @pytest.mark.asyncio
    async def test_send_message_stream_true_by_default(self):
        client = ClothoWebSocketClient("localhost", 8000, "chat-1", "token")
        client.ws = AsyncMock()

        await client.send_message("Hello")

        client.ws.send.assert_called_once()
        sent = json.loads(client.ws.send.call_args[0][0])
        assert sent["type"] == "run"
        assert sent["data"]["message"] == "Hello"
        assert sent["data"]["stream"] is True

    @pytest.mark.asyncio
    async def test_send_message_stream_false(self):
        client = ClothoWebSocketClient("localhost", 8000, "chat-1", "token")
        client.ws = AsyncMock()

        await client.send_message("Hello", stream=False)

        sent = json.loads(client.ws.send.call_args[0][0])
        assert sent["data"]["stream"] is False

    @pytest.mark.asyncio
    async def test_send_message_stream_explicit_true(self):
        client = ClothoWebSocketClient("localhost", 8000, "chat-1", "token")
        client.ws = AsyncMock()

        await client.send_message("Hello", stream=True)

        sent = json.loads(client.ws.send.call_args[0][0])
        assert sent["data"]["stream"] is True


# ---------------------------------------------------------------------------
# REPL streaming toggle
# ---------------------------------------------------------------------------

class TestREPLStreamToggle:
    def _make_repl(self):
        with patch("cli.repl.ClothoAPIClient"), \
             patch("cli.repl.ClothoWebSocketClient"), \
             patch("cli.repl.GatewayManager"):
            from cli.repl import ClothoREPL
            return ClothoREPL("localhost", 8000)

    def test_streaming_defaults_true(self):
        repl = self._make_repl()
        assert repl.streaming is True

    def test_handle_stream_on(self):
        repl = self._make_repl()
        repl.streaming = False
        repl.handle_stream(["on"])
        assert repl.streaming is True

    def test_handle_stream_off(self):
        repl = self._make_repl()
        repl.handle_stream(["off"])
        assert repl.streaming is False

    def test_handle_stream_no_args_shows_status(self, capsys):
        repl = self._make_repl()
        # Just verify it doesn't crash — output goes through Rich console
        repl.handle_stream([])
        assert repl.streaming is True  # unchanged

    def test_handle_stream_invalid_arg(self):
        repl = self._make_repl()
        original = repl.streaming
        repl.handle_stream(["maybe"])
        assert repl.streaming == original  # unchanged


# ---------------------------------------------------------------------------
# REPL message handler accepts text_delta
# ---------------------------------------------------------------------------

class TestREPLMessageHandler:
    def _make_repl(self):
        with patch("cli.repl.ClothoAPIClient"), \
             patch("cli.repl.ClothoWebSocketClient"), \
             patch("cli.repl.GatewayManager"):
            from cli.repl import ClothoREPL
            return ClothoREPL("localhost", 8000)

    def test_handles_text_delta(self):
        repl = self._make_repl()
        # Should not raise
        repl.handle_message({
            "type": "agent.text_delta",
            "data": {"text": "Hello"},
        })

    def test_handles_text_batch(self):
        repl = self._make_repl()
        # Should not raise
        repl.handle_message({
            "type": "agent.text",
            "data": {"text": "Hello"},
        })

    def test_turn_complete_signals_event(self):
        repl = self._make_repl()
        repl.handle_message({
            "type": "agent.turn_complete",
            "data": {"stop_reason": "end_turn", "model": "test", "usage": {}},
        })
        assert repl.response_complete.is_set()
