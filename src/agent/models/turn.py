from pydantic import BaseModel, Field
from typing import Annotated, Literal, Union

from agent.models.content_block import ContentBlock
from agent.models.stop_reason import StopReason
from agent.models.usage import Usage

class AssistantTurn(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str | list[ContentBlock]
    model: str
    stop_reason: Literal[StopReason]
    usage: Usage

class SystemTurn(BaseModel):
    role: Literal["system"] = "system"
    content: str

class UserTurn(BaseModel):
    role: Literal["user"] = "user"
    content: str | list[ContentBlock]

class ToolTurn(BaseModel):
    role: Literal["tool"] = "tool"
    content: str | list[ContentBlock]

class CompactionTurn(BaseModel):
    """Marker written to JSONL when context compaction occurs.

    On load, everything before the last CompactionTurn is ignored —
    the turns that follow it constitute the active context.
    """
    role: Literal["compaction"] = "compaction"
    timestamp: str          # ISO-8601 UTC
    turns_removed: int
    tokens_before: int
    tokens_after: int | None = None

Turn = Annotated[
    Union[AssistantTurn, SystemTurn, UserTurn, ToolTurn, CompactionTurn],
    Field(discriminator="role")
]
