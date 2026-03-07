from pydantic import BaseModel

from agent.models.metadata import Metadata
from agent.models.turn import Turn
from agent.models.usage import Usage


class ConversationContext(BaseModel):
    turns: list[Turn]
    token_usage: Usage
    metadata: Metadata
    current_step: int = 0