"""Tests for ClothoController streaming support."""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from agent.models.content_block import TextContent, ToolUseContent, ToolResultContent
from agent.models.stream_delta import StreamDelta
from agent.models.tool import Tool
from agent.models.turn import AssistantTurn, SystemTurn, UserTurn, ToolTurn
from agent.models.usage import Usage
from exceptions import NoModelConfiguredError, NoActiveChatError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assistant_turn(content="Hello", stop_reason="end_turn"):
    return AssistantTurn(
        content=content,
        model="test-model",
        stop_reason=stop_reason,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def _make_tool_assistant_turn():
    return AssistantTurn(
        content=[
            TextContent(text="Let me run that."),
            ToolUseContent(id="call_1", name="bash", arguments={"command": "ls"}),
        ],
        model="test-model",
        stop_reason="tool_use",
        usage=Usage(input_tokens=10, output_tokens=8),
    )


def _text_deltas(text_chunks, assistant_turn):
    """Create a sequence of StreamDeltas for a simple text response."""
    deltas = [StreamDelta(type="text_delta", text=chunk) for chunk in text_chunks]
    deltas.append(StreamDelta(type="message_complete", assistant_turn=assistant_turn))
    return deltas


def _tool_deltas(assistant_turn):
    """Create a sequence of StreamDeltas for a tool use response."""
    return [
        StreamDelta(type="text_delta", text="Let me run that."),
        StreamDelta(type="tool_use_start", tool_call_id="call_1", tool_call_name="bash"),
        StreamDelta(type="tool_use_delta", text='{"command": "ls"}', tool_call_id="call_1"),
        StreamDelta(type="message_complete", assistant_turn=assistant_turn),
    ]


def _make_controller():
    """Create a ClothoController with mocked dependencies."""
    with patch("agent.core.load_dotenv"), \
         patch("agent.core.is_sandbox_enabled", return_value=False):
        from agent.core import ClothoController
        ctrl = ClothoController()
        ctrl.context = [SystemTurn(content="You are helpful.")]
        ctrl.model = MagicMock()
        # Stub checkpoint_turn to avoid file I/O
        ctrl.checkpoint_turn = MagicMock(return_value=True)
        return ctrl


# ---------------------------------------------------------------------------
# stream_invoke
# ---------------------------------------------------------------------------

class TestControllerStreamInvoke:
    def test_stream_invoke_yields_deltas(self):
        ctrl = _make_controller()
        turn = _make_assistant_turn()
        deltas = _text_deltas(["Hi", " there"], turn)
        ctrl.model.stream_invoke.return_value = iter(deltas)

        result = list(ctrl.stream_invoke(UserTurn(content="Hello")))

        assert len(result) == 3  # 2 text + 1 complete
        assert result[0].type == "text_delta"
        assert result[2].type == "message_complete"

    def test_stream_invoke_appends_to_context(self):
        ctrl = _make_controller()
        turn = _make_assistant_turn()
        deltas = _text_deltas(["Hi"], turn)
        ctrl.model.stream_invoke.return_value = iter(deltas)

        list(ctrl.stream_invoke(UserTurn(content="Hello")))

        # Context should have: system + user + assistant
        assert len(ctrl.context) == 3
        assert ctrl.context[-1] is turn

    def test_stream_invoke_checkpoints(self):
        ctrl = _make_controller()
        turn = _make_assistant_turn()
        deltas = _text_deltas(["Hi"], turn)
        ctrl.model.stream_invoke.return_value = iter(deltas)

        list(ctrl.stream_invoke(UserTurn(content="Hello")))

        ctrl.checkpoint_turn.assert_called_once()

    def test_stream_invoke_no_model_raises(self):
        ctrl = _make_controller()
        ctrl.model = None

        with pytest.raises(NoModelConfiguredError):
            list(ctrl.stream_invoke(UserTurn(content="Hello")))

    def test_stream_invoke_no_context_raises(self):
        ctrl = _make_controller()
        ctrl.context = None

        with pytest.raises(NoActiveChatError):
            list(ctrl.stream_invoke(UserTurn(content="Hello")))


# ---------------------------------------------------------------------------
# run() with stream=True
# ---------------------------------------------------------------------------

class TestControllerRunStreaming:
    @pytest.mark.asyncio
    async def test_run_stream_emits_text_deltas(self):
        ctrl = _make_controller()
        turn = _make_assistant_turn()
        deltas = _text_deltas(["Hi", " there"], turn)
        ctrl.model.stream_invoke.return_value = iter(deltas)

        emitted = []

        async def mock_emit(event_type, data):
            emitted.append((event_type, data))

        async def mock_approval(tool_calls):
            return {}

        await ctrl.run("Hello", emit=mock_emit, request_approval=mock_approval, stream=True)

        text_events = [(t, d) for t, d in emitted if t == "agent.text_delta"]
        assert len(text_events) == 2
        assert text_events[0][1]["text"] == "Hi"
        assert text_events[1][1]["text"] == " there"

        # Should end with turn_complete
        assert emitted[-1][0] == "agent.turn_complete"

    @pytest.mark.asyncio
    async def test_run_stream_false_uses_batch(self):
        ctrl = _make_controller()
        turn = _make_assistant_turn()
        ctrl.model.invoke.return_value = turn

        emitted = []

        async def mock_emit(event_type, data):
            emitted.append((event_type, data))

        async def mock_approval(tool_calls):
            return {}

        await ctrl.run("Hello", emit=mock_emit, request_approval=mock_approval, stream=False)

        # Should use agent.text (batch), not agent.text_delta
        text_events = [t for t, d in emitted if t == "agent.text"]
        assert len(text_events) == 1

        delta_events = [t for t, d in emitted if t == "agent.text_delta"]
        assert len(delta_events) == 0

    @pytest.mark.asyncio
    async def test_run_stream_with_tool_use(self):
        ctrl = _make_controller()
        ctrl.tools = [Tool(
            name="bash",
            description="Run command",
            parameters={"type": "object", "properties": {}},
            func=lambda: "result",
        )]

        tool_turn = _make_tool_assistant_turn()
        final_turn = _make_assistant_turn("Done!")

        call_count = 0

        def mock_stream_invoke(context, tools, max_tokens):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return iter(_tool_deltas(tool_turn))
            else:
                return iter(_text_deltas(["Done!"], final_turn))

        ctrl.model.stream_invoke.side_effect = mock_stream_invoke

        emitted = []

        async def mock_emit(event_type, data):
            emitted.append((event_type, data))

        async def mock_approval(tool_calls):
            return {tc["id"]: "allow" for tc in tool_calls}

        await ctrl.run("Do something", emit=mock_emit, request_approval=mock_approval, stream=True)

        event_types = [t for t, d in emitted]
        assert "agent.text_delta" in event_types
        assert "agent.tool_use_start" in event_types
        assert "agent.tool_result" in event_types
        assert "agent.turn_complete" in event_types
