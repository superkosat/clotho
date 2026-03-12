"""Tests for gateway streaming plumbing (events model and service)."""

import pytest

from gateway.models.events import RunData, parse_client_event


class TestRunDataStream:
    def test_stream_defaults_false(self):
        data = RunData(message="Hello")
        assert data.stream is False

    def test_stream_true(self):
        data = RunData(message="Hello", stream=True)
        assert data.stream is True

    def test_stream_false_explicit(self):
        data = RunData(message="Hello", stream=False)
        assert data.stream is False


class TestParseClientEventStream:
    def test_run_event_with_stream(self):
        event_type, data = parse_client_event({
            "type": "run",
            "data": {"message": "Hello", "stream": True},
        })
        assert event_type == "run"
        assert data["stream"] is True

    def test_run_event_without_stream(self):
        event_type, data = parse_client_event({
            "type": "run",
            "data": {"message": "Hello"},
        })
        assert event_type == "run"
        # stream not in data dict, but RunData validation passes (default False)
        assert data.get("stream", False) is False

    def test_invalid_event_type_raises(self):
        with pytest.raises(ValueError, match="Unknown client event type"):
            parse_client_event({"type": "invalid", "data": {}})

    def test_tool_approval_unchanged(self):
        event_type, data = parse_client_event({
            "type": "tool_approval",
            "data": {"approved": True},
        })
        assert event_type == "tool_approval"
        assert data["approved"] is True
