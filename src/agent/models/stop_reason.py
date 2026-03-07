from typing import Literal

StopReason = Literal[
    "end_turn",
    "max_tokens",
    "tool_use",
    "stop_sequence",
    "content_filter",
    "error",
]