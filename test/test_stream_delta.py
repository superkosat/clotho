"""Tests for the StreamDelta model."""

import pytest
from pydantic import ValidationError

from agent.models.stream_delta import StreamDelta
from agent.models.turn import AssistantTurn
from agent.models.usage import Usage


class TestStreamDeltaTextDelta:
    def test_text_delta_with_text(self):
        delta = StreamDelta(type="text_delta", text="Hello")
        assert delta.type == "text_delta"
        assert delta.text == "Hello"
        assert delta.tool_call_id is None
        assert delta.assistant_turn is None

    def test_text_delta_empty_string(self):
        delta = StreamDelta(type="text_delta", text="")
        assert delta.text == ""


class TestStreamDeltaToolUse:
    def test_tool_use_start(self):
        delta = StreamDelta(
            type="tool_use_start",
            tool_call_id="call_123",
            tool_call_name="bash",
        )
        assert delta.type == "tool_use_start"
        assert delta.tool_call_id == "call_123"
        assert delta.tool_call_name == "bash"

    def test_tool_use_delta(self):
        delta = StreamDelta(
            type="tool_use_delta",
            text='{"command": "ls"}',
            tool_call_id="call_123",
        )
        assert delta.type == "tool_use_delta"
        assert delta.text == '{"command": "ls"}'
        assert delta.tool_call_id == "call_123"


class TestStreamDeltaMessageComplete:
    def test_message_complete_with_turn(self):
        turn = AssistantTurn(
            content="Hello world",
            model="test-model",
            stop_reason="end_turn",
            usage=Usage(input_tokens=10, output_tokens=5),
        )
        delta = StreamDelta(type="message_complete", assistant_turn=turn)
        assert delta.type == "message_complete"
        assert delta.assistant_turn is turn
        assert delta.assistant_turn.content == "Hello world"
        assert delta.assistant_turn.model == "test-model"

    def test_message_complete_none_turn(self):
        delta = StreamDelta(type="message_complete")
        assert delta.assistant_turn is None


class TestStreamDeltaValidation:
    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            StreamDelta(type="invalid_type")

    def test_all_optional_fields_default_none(self):
        delta = StreamDelta(type="text_delta")
        assert delta.text is None
        assert delta.tool_call_id is None
        assert delta.tool_call_name is None
        assert delta.assistant_turn is None
