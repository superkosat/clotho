from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime, timezone


# --- Server-to-Client event data ---

class AgentTextData(BaseModel):
    text: str

class ToolCallInfo(BaseModel):
    id: str
    name: str
    arguments: dict

class AgentToolRequestData(BaseModel):
    tool_calls: list[ToolCallInfo]

class AgentToolResultData(BaseModel):
    tool_use_id: str
    tool_name: str
    content: str
    is_error: bool = False

class AgentTurnCompleteData(BaseModel):
    stop_reason: str
    model: str
    usage: dict

class AgentToolDeniedData(BaseModel):
    tool_calls: list[ToolCallInfo]
    reason: str

class AgentErrorData(BaseModel):
    code: str
    message: str


# --- Client-to-Server event data ---

class RunData(BaseModel):
    message: str
    stream: bool = False

class ToolApprovalData(BaseModel):
    approved: bool


# --- Envelope ---

class ServerEvent(BaseModel):
    type: str
    data: dict
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_json(self) -> dict:
        return {
            "type": self.type,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


def parse_client_event(raw: dict) -> tuple[str, dict]:
    """Validate and extract type + data from a client message."""
    event_type = raw.get("type")
    data = raw.get("data", {})

    if event_type not in ("run", "tool_approval", "cancel", "panic"):
        raise ValueError(f"Unknown client event type: {event_type}")

    if event_type == "run":
        RunData(**data)
    elif event_type == "tool_approval":
        ToolApprovalData(**data)

    return event_type, data
