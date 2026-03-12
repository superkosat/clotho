import asyncio
import logging
import traceback
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from gateway.auth.token import verify_token
from gateway.models.events import parse_client_event
from gateway.service import AgentService

router = APIRouter()


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

    service = AgentService(session, websocket)
    run_task: asyncio.Task | None = None

    try:
        while True:
            raw = await websocket.receive_json()

            try:
                event_type, data = parse_client_event(raw)
            except ValueError as e:
                # Invalid event format - send error but don't disconnect
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
                    run_task = asyncio.create_task(
                        service.handle_run(data["message"], stream=data.get("stream", False))
                    )
                case "tool_approval":
                    service.handle_tool_approval(data)
                case "cancel":
                    service.handle_cancel()

    except WebSocketDisconnect:
        service.handle_disconnect()
        if run_task and not run_task.done():
            run_task.cancel()
    except Exception as e:
        logger.error("WebSocket error: %s\n%s", e, traceback.format_exc())
        service.handle_disconnect()
        if run_task and not run_task.done():
            run_task.cancel()
