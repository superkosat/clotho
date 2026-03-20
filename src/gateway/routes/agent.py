import asyncio
import logging
import traceback
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

from gateway.auth.token import verify_token
from gateway.dispatcher import GatewayEvent, EventPriority
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
                    event = GatewayEvent(
                        type="run",
                        data=data,
                        priority=EventPriority.NORMAL,
                        source="websocket",
                    )
                    session.dispatcher.submit(
                        event,
                        lambda m=msg, s=stream: service.handle_run(m, s),
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
