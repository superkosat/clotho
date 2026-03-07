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

Turn = Annotated[
    Union[AssistantTurn, SystemTurn, UserTurn, ToolTurn],
    Field(discriminator="role")
]
    