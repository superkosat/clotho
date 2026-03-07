from pydantic import BaseModel


class ChatResponse(BaseModel):
    chat_id: str


class ChatListResponse(BaseModel):
    chats: list[dict]


class HealthResponse(BaseModel):
    status: str
    active_sessions: int


class UpdatePermissionsRequest(BaseModel):
    mode: str | None = None
    tool_overrides: dict[str, str] | None = None


class SetActiveProfileRequest(BaseModel):
    profile_name: str


class ActiveProfileResponse(BaseModel):
    profile_name: str | None
