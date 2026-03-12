from typing import Literal

from pydantic import BaseModel

from agent.models.turn import AssistantTurn


class StreamDelta(BaseModel):
    type: Literal[
        "text_delta",
        "tool_use_start",
        "tool_use_delta",
        "message_complete",
    ]

    # text_delta
    text: str | None = None

    # tool_use_start / tool_use_delta
    tool_call_id: str | None = None
    tool_call_name: str | None = None

    # message_complete
    assistant_turn: AssistantTurn | None = None
