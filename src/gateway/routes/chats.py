from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from gateway.models.requests import ChatResponse, ChatListResponse

router = APIRouter(prefix="/api/chats", tags=["chats"])


@router.post("", response_model=ChatResponse, status_code=201)
def create_chat(request: Request):
    manager = request.app.state.session_manager
    chat_id, _ = manager.create_session()
    return ChatResponse(chat_id=str(chat_id))


@router.get("", response_model=ChatListResponse)
def list_chats(request: Request):
    manager = request.app.state.session_manager
    chat_ids = manager.list_chats()
    return ChatListResponse(chats=[{"chat_id": cid} for cid in chat_ids])


@router.get("/{chat_id}")
def get_chat(chat_id: UUID, request: Request):
    manager = request.app.state.session_manager
    try:
        session = manager.get_or_load_session(chat_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Chat not found")

    turns = []
    for turn in session.controller.context:
        turns.append(turn.model_dump())

    return {"chat_id": str(chat_id), "turns": turns}


@router.get("/{chat_id}/context")
def get_context_info(chat_id: UUID, request: Request):
    """Get context window usage for a chat session."""
    manager = request.app.state.session_manager
    try:
        session = manager.get_or_load_session(chat_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Chat not found")

    ctrl = session.controller
    if not ctrl.context or not ctrl.model:
        raise HTTPException(status_code=400, detail="No active model or context")

    try:
        current_tokens = ctrl.model.count_tokens(ctrl.context, ctrl.tools)
    except Exception:
        current_tokens = ctrl._estimate_tokens_heuristic()

    return {
        "current_tokens": current_tokens,
        "context_window": ctrl.context_window,
        "compaction_threshold": 0.75,
    }


@router.post("/{chat_id}/compact")
async def compact_chat(chat_id: UUID, request: Request):
    """Manually trigger context compaction for a chat session."""
    manager = request.app.state.session_manager
    try:
        session = manager.get_or_load_session(chat_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Chat not found")

    try:
        metadata = await session.controller.compact_context()
        return metadata
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{chat_id}")
def delete_chat(chat_id: UUID, request: Request):
    manager = request.app.state.session_manager

    session = manager.get_session(chat_id)
    if session:
        session.controller.delete_chat()
        manager.remove_session(chat_id)
    else:
        from agent.utils.projects import delete_project_file
        delete_project_file(chat_id)

    return {"deleted": True}
