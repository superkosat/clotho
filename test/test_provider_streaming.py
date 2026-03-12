"""Tests for provider stream_invoke methods using mocked SDK clients."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agent.models.content_block import TextContent, ToolUseContent
from agent.models.stream_delta import StreamDelta
from agent.models.tool import Tool
from agent.models.turn import AssistantTurn, SystemTurn, UserTurn
from agent.models.usage import Usage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_tool():
    return Tool(
        name="bash",
        description="Run a command",
        parameters={"type": "object", "properties": {"command": {"type": "string"}}},
        func=lambda command: command,
    )


def _system_and_user_turns():
    return [
        SystemTurn(content="You are helpful."),
        UserTurn(content="Hello"),
    ]


def _collect(iterator):
    """Drain an iterator into a list."""
    return list(iterator)


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

class TestAnthropicStreamInvoke:
    def _make_event(self, event_type, **kwargs):
        e = MagicMock()
        e.type = event_type
        for k, v in kwargs.items():
            setattr(e, k, v)
        return e

    def _make_text_stream(self, text_chunks):
        """Simulate Anthropic streaming events for a simple text response."""
        msg_start = self._make_event("message_start")
        msg_start.message = MagicMock()
        msg_start.message.model = "claude-test"
        msg_start.message.usage = MagicMock()
        msg_start.message.usage.input_tokens = 10

        block_start = self._make_event("content_block_start")
        block_start.content_block = MagicMock()
        block_start.content_block.type = "text"

        deltas = []
        for chunk in text_chunks:
            d = self._make_event("content_block_delta")
            d.delta = MagicMock()
            d.delta.type = "text_delta"
            d.delta.text = chunk
            deltas.append(d)

        block_stop = self._make_event("content_block_stop")

        msg_delta = self._make_event("message_delta")
        msg_delta.delta = MagicMock()
        msg_delta.delta.stop_reason = "end_turn"
        msg_delta.usage = MagicMock()
        msg_delta.usage.output_tokens = 5

        return [msg_start, block_start, *deltas, block_stop, msg_delta]

    def _make_tool_stream(self, tool_id, tool_name, args_json_chunks):
        """Simulate Anthropic streaming events for a tool use response."""
        msg_start = self._make_event("message_start")
        msg_start.message = MagicMock()
        msg_start.message.model = "claude-test"
        msg_start.message.usage = MagicMock()
        msg_start.message.usage.input_tokens = 15

        block_start = self._make_event("content_block_start")
        block_start.content_block = MagicMock()
        block_start.content_block.type = "tool_use"
        block_start.content_block.id = tool_id
        block_start.content_block.name = tool_name

        deltas = []
        for chunk in args_json_chunks:
            d = self._make_event("content_block_delta")
            d.delta = MagicMock()
            d.delta.type = "input_json_delta"
            d.delta.partial_json = chunk
            deltas.append(d)

        block_stop = self._make_event("content_block_stop")

        msg_delta = self._make_event("message_delta")
        msg_delta.delta = MagicMock()
        msg_delta.delta.stop_reason = "tool_use"
        msg_delta.usage = MagicMock()
        msg_delta.usage.output_tokens = 8

        return [msg_start, block_start, *deltas, block_stop, msg_delta]

    @patch("agent.providers.anthropic.anthropic")
    def test_text_streaming(self, mock_anthropic_mod):
        from agent.providers.anthropic import AnthropicModel

        events = self._make_text_stream(["Hel", "lo ", "world"])
        mock_client = MagicMock()
        mock_anthropic_mod.Anthropic.return_value = mock_client

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=iter(events))
        ctx.__exit__ = MagicMock(return_value=False)
        mock_client.messages.stream.return_value = ctx

        model = AnthropicModel(model="claude-test", api_key="fake")
        deltas = _collect(model.stream_invoke(_system_and_user_turns(), None, 4000))

        text_deltas = [d for d in deltas if d.type == "text_delta"]
        assert len(text_deltas) == 3
        assert text_deltas[0].text == "Hel"
        assert text_deltas[1].text == "lo "
        assert text_deltas[2].text == "world"

        complete = [d for d in deltas if d.type == "message_complete"]
        assert len(complete) == 1
        turn = complete[0].assistant_turn
        assert turn.content == "Hello world"
        assert turn.stop_reason == "end_turn"
        assert turn.usage.input_tokens == 10
        assert turn.usage.output_tokens == 5

    @patch("agent.providers.anthropic.anthropic")
    def test_tool_use_streaming(self, mock_anthropic_mod):
        from agent.providers.anthropic import AnthropicModel

        events = self._make_tool_stream(
            "call_1", "bash", ['{"comma', 'nd": "ls"}']
        )
        mock_client = MagicMock()
        mock_anthropic_mod.Anthropic.return_value = mock_client

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=iter(events))
        ctx.__exit__ = MagicMock(return_value=False)
        mock_client.messages.stream.return_value = ctx

        model = AnthropicModel(model="claude-test", api_key="fake")
        deltas = _collect(model.stream_invoke(
            _system_and_user_turns(), [_dummy_tool()], 4000
        ))

        starts = [d for d in deltas if d.type == "tool_use_start"]
        assert len(starts) == 1
        assert starts[0].tool_call_id == "call_1"
        assert starts[0].tool_call_name == "bash"

        arg_deltas = [d for d in deltas if d.type == "tool_use_delta"]
        assert len(arg_deltas) == 2

        complete = [d for d in deltas if d.type == "message_complete"]
        turn = complete[0].assistant_turn
        assert turn.stop_reason == "tool_use"
        assert isinstance(turn.content, list)
        tool_block = turn.content[0]
        assert isinstance(tool_block, ToolUseContent)
        assert tool_block.arguments == {"command": "ls"}


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

class TestOpenAIStreamInvoke:
    def _make_text_chunks(self, texts):
        """Simulate OpenAI streaming chunks for text."""
        chunks = []
        for text in texts:
            chunk = MagicMock()
            chunk.model = "gpt-test"
            chunk.usage = None
            chunk.choices = [MagicMock()]
            chunk.choices[0].finish_reason = None
            chunk.choices[0].delta = MagicMock()
            chunk.choices[0].delta.content = text
            chunk.choices[0].delta.tool_calls = None
            chunks.append(chunk)

        # Final chunk with finish_reason and usage
        final = MagicMock()
        final.model = "gpt-test"
        final.usage = MagicMock()
        final.usage.prompt_tokens = 12
        final.usage.completion_tokens = 6
        final.choices = [MagicMock()]
        final.choices[0].finish_reason = "stop"
        final.choices[0].delta = MagicMock()
        final.choices[0].delta.content = None
        final.choices[0].delta.tool_calls = None
        chunks.append(final)

        return chunks

    def _make_tool_chunks(self, tool_id, tool_name, arg_chunks):
        """Simulate OpenAI streaming chunks for a tool call."""
        chunks = []

        # First chunk: tool_call start
        first = MagicMock()
        first.model = "gpt-test"
        first.usage = None
        first.choices = [MagicMock()]
        first.choices[0].finish_reason = None
        first.choices[0].delta = MagicMock()
        first.choices[0].delta.content = None
        tc_delta = MagicMock()
        tc_delta.index = 0
        tc_delta.id = tool_id
        tc_delta.function = MagicMock()
        tc_delta.function.name = tool_name
        tc_delta.function.arguments = arg_chunks[0]
        first.choices[0].delta.tool_calls = [tc_delta]
        chunks.append(first)

        # Subsequent arg chunks
        for arg_chunk in arg_chunks[1:]:
            c = MagicMock()
            c.model = "gpt-test"
            c.usage = None
            c.choices = [MagicMock()]
            c.choices[0].finish_reason = None
            c.choices[0].delta = MagicMock()
            c.choices[0].delta.content = None
            tc = MagicMock()
            tc.index = 0
            tc.id = None
            tc.function = MagicMock()
            tc.function.name = None
            tc.function.arguments = arg_chunk
            c.choices[0].delta.tool_calls = [tc]
            chunks.append(c)

        # Final chunk
        final = MagicMock()
        final.model = "gpt-test"
        final.usage = MagicMock()
        final.usage.prompt_tokens = 20
        final.usage.completion_tokens = 10
        final.choices = [MagicMock()]
        final.choices[0].finish_reason = "tool_calls"
        final.choices[0].delta = MagicMock()
        final.choices[0].delta.content = None
        final.choices[0].delta.tool_calls = None
        chunks.append(final)

        return chunks

    @patch("agent.providers.openai.openai")
    def test_text_streaming(self, mock_openai_mod):
        from agent.providers.openai import OpenAIModel

        chunks = self._make_text_chunks(["Hi", " there"])
        mock_client = MagicMock()
        mock_openai_mod.Client.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter(chunks)

        model = OpenAIModel(model="gpt-test", base_url="http://fake", api_key="fake")
        deltas = _collect(model.stream_invoke(_system_and_user_turns(), None, 4000))

        text_deltas = [d for d in deltas if d.type == "text_delta"]
        assert len(text_deltas) == 2
        assert text_deltas[0].text == "Hi"
        assert text_deltas[1].text == " there"

        complete = [d for d in deltas if d.type == "message_complete"]
        assert len(complete) == 1
        turn = complete[0].assistant_turn
        assert turn.content == "Hi there"
        assert turn.stop_reason == "end_turn"

    @patch("agent.providers.openai.openai")
    def test_tool_use_streaming(self, mock_openai_mod):
        from agent.providers.openai import OpenAIModel

        chunks = self._make_tool_chunks("call_1", "bash", ['{"comm', 'and": "pwd"}'])
        mock_client = MagicMock()
        mock_openai_mod.Client.return_value = mock_client
        mock_client.chat.completions.create.return_value = iter(chunks)

        model = OpenAIModel(model="gpt-test", base_url="http://fake", api_key="fake")
        deltas = _collect(model.stream_invoke(
            _system_and_user_turns(), [_dummy_tool()], 4000
        ))

        starts = [d for d in deltas if d.type == "tool_use_start"]
        assert len(starts) == 1
        assert starts[0].tool_call_name == "bash"

        complete = [d for d in deltas if d.type == "message_complete"]
        turn = complete[0].assistant_turn
        assert turn.stop_reason == "tool_use"
        assert isinstance(turn.content, list)
        tool_block = turn.content[0]
        assert isinstance(tool_block, ToolUseContent)
        assert tool_block.arguments == {"command": "pwd"}


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

class TestOllamaStreamInvoke:
    def _make_text_chunks(self, texts):
        chunks = []
        for text in texts:
            c = MagicMock()
            c.model = "llama-test"
            c.message = MagicMock()
            c.message.content = text
            c.message.tool_calls = None
            c.prompt_eval_count = None
            c.eval_count = None
            c.done_reason = None
            chunks.append(c)

        # Final chunk with usage
        final = MagicMock()
        final.model = "llama-test"
        final.message = MagicMock()
        final.message.content = ""
        final.message.tool_calls = None
        final.prompt_eval_count = 8
        final.eval_count = 4
        final.done_reason = "stop"
        chunks.append(final)

        return chunks

    @patch("agent.providers.ollama.chat")
    def test_text_streaming(self, mock_chat):
        from agent.providers.ollama import OllamaModel

        chunks = self._make_text_chunks(["Hey", " there"])
        mock_chat.return_value = iter(chunks)

        model = OllamaModel(model="llama-test")
        deltas = _collect(model.stream_invoke(_system_and_user_turns(), None, 4000))

        text_deltas = [d for d in deltas if d.type == "text_delta"]
        # "Hey", " there", and "" (final chunk) — only non-empty yield
        assert len(text_deltas) == 2
        assert text_deltas[0].text == "Hey"

        complete = [d for d in deltas if d.type == "message_complete"]
        assert len(complete) == 1
        turn = complete[0].assistant_turn
        assert turn.content == "Hey there"
        assert turn.stop_reason == "end_turn"
        assert turn.usage.input_tokens == 8
