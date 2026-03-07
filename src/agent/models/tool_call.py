from pydantic import BaseModel
from typing import Any

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict
    result: Any | None = None
    error: str | None = None
    duration_ms: float | None = None
    
    