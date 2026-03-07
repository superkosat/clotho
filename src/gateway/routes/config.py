from uuid import UUID
from fastapi import APIRouter, HTTPException, Request

from gateway.models.requests import SetActiveProfileRequest, ActiveProfileResponse

router = APIRouter(prefix="/api/chats", tags=["config"])


@router.get("/{chat_id}/active-profile")
def get_active_profile(chat_id: UUID, request: Request) -> ActiveProfileResponse:
    """Get the currently active model profile for a chat session."""
    session_manager = request.app.state.session_manager
    try:
        profile_name = session_manager.get_active_profile(chat_id)
        return ActiveProfileResponse(profile_name=profile_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{chat_id}/active-profile")
def set_active_profile(
    chat_id: UUID, body: SetActiveProfileRequest, request: Request
) -> ActiveProfileResponse:
    """Switch the active model profile for a chat session."""
    session_manager = request.app.state.session_manager
    try:
        session_manager.switch_profile(chat_id, body.profile_name)
        return ActiveProfileResponse(profile_name=body.profile_name)
    except ValueError as e:
        # Could be session not found or profile not found
        raise HTTPException(status_code=404, detail=str(e))
