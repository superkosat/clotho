import asyncio
import logging
import traceback
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from gateway.auth.dependencies import require_token
from gateway.auth.token import verify_token
from gateway.dispatcher import GatewayEvent, EventPriority
from gateway.models.events import parse_client_event
from gateway.service import AgentService

router = APIRouter()


@router.post("/api/chats/{chat_id}/cancel", dependencies=[Depends(require_token)])
async def cancel_chat(chat_id: UUID, request: Request):
    """
    Cancel the active run for a session. Queued runs proceed after this.
    Safe to call from any transport — REST, bridge, scheduler.
    """
    manager = request.app.state.session_manager
    session = manager.get_session(chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not active")

    session.cancel_event.set()
    if session.pending_approval and not session.pending_approval.done():
        session.pending_approval.set_result({"approved": False})
    session.dispatcher.cancel_current()
    return {"cancelled": True}


@router.post("/api/chats/{chat_id}/panic", dependencies=[Depends(require_token)])
async def panic_chat(chat_id: UUID, request: Request):
    """
    Cancel the active run and drain all queued work for a session.
    Nothing further will execute until a new run is submitted.
    """
    manager = request.app.state.session_manager
    session = manager.get_session(chat_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not active")

    session.cancel_event.set()
    if session.pending_approval and not session.pending_approval.done():
        session.pending_approval.set_result({"approved": False})
    session.dispatcher.cancel_current()
    session.dispatcher.drain()
    return {"panicked": True}


@router.post("/api/panic", dependencies=[Depends(require_token)])
async def panic_all(request: Request):
    """
    Cancel all active sessions and drain their queues (global stop-all).
    """
    manager = request.app.state.session_manager
    count = manager.panic_all()
    return {"panicked": True, "sessions_affected": count}


@router.websocket("/ws/{chat_id}")
async def agent_websocket(websocket: WebSocket, chat_id: UUID):
    token = websocket.query_params.get("token")
    if not token or not verify_token(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    manager = websocket.app.state.session_manager
    try:
        session = await asyncio.to_thread(manager.get_or_load_session, chat_id)
    except ValueError:
        await websocket.close(code=4004, reason="Chat not found")
        return

    # Start the dispatcher consumer loop for this session. Idempotent — safe
    # on reconnect. The dispatcher persists for the lifetime of the session;
    # this just ensures the consumer task is running.
    session.dispatcher.start()

    service = AgentService(session, websocket)

    try:
        while True:
            raw = await websocket.receive_json()

            try:
                event_type, data = parse_client_event(raw)
            except ValueError as e:
                await websocket.send_json({
                    "type": "agent.error",
                    "data": {
                        "code": "invalid_event",
                        "message": str(e)
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                continue

            match event_type:
                case "run":
                    # Capture loop-local values to avoid closure over the
                    # loop variable `data` being mutated in later iterations.
                    msg = data["message"]
                    stream = data.get("stream", False)
                    content = data.get("content")  # optional multi-modal content blocks
                    event = GatewayEvent(
                        type="run",
                        data=data,
                        priority=EventPriority.NORMAL,
                        source="websocket",
                    )
                    session.dispatcher.submit(
                        event,
                        lambda m=msg, s=stream, c=content: service.handle_run(m, s, content=c),
                    )
                case "tool_approval":
                    # Tool approvals resolve the pending future in the currently
                    # running handler — they must never be queued.
                    service.handle_tool_approval(data)
                case "cancel":
                    # Critical: cancel current run. Queued runs still proceed.
                    session.dispatcher.execute_critical(service.handle_cancel)
                case "panic":
                    # Critical: cancel current run AND drain the queue.
                    # Nothing queued will start after this.
                    session.dispatcher.execute_critical(service.handle_panic)

    except WebSocketDisconnect:
        session.dispatcher.execute_critical(service.handle_disconnect)
    except Exception as e:
        logger.error("WebSocket error: %s\n%s", e, traceback.format_exc())
        session.dispatcher.execute_critical(service.handle_disconnect)
