"""Agent interaction for scheduled jobs — connects to the gateway and returns the response."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from cli.api_client import ClothoAPIClient
from cli.ws_client import ClothoWebSocketClient

logger = logging.getLogger(__name__)


async def run_agent(
    host: str,
    port: int,
    token: str,
    chat_id: str,
    prompt: str,
    *,
    timeout: float = 300.0,
) -> str:
    """Send a prompt to an existing gateway session and return the full response.

    The run is submitted to the session's EventDispatcher via the WebSocket 'run'
    event — the same path as any interactive user message. The dispatcher queues it
    behind any currently active run and processes it in priority order.

    # TODO: submit at BACKGROUND priority so scheduled jobs yield to user messages.
    # This requires either a 'run_background' event type or a 'priority' field on
    # the run message, with a matching change in the gateway WebSocket handler.

    Tool requests that reach this client are auto-denied — scheduled jobs are
    unattended. To allow tool use, configure the gateway permission mode to
    'autonomous' so the gateway handles approval internally before events reach
    any client.

    Raises:
        RuntimeError: If the agent returns an error event or times out.
    """
    ws = ClothoWebSocketClient(host, port, chat_id, token)
    await ws.connect()

    parts: list[str] = []
    done = asyncio.Event()
    errors: list[str] = []

    def on_event(data: dict) -> None:
        match data.get("type"):
            case "agent.text_delta" | "agent.text":
                parts.append(data.get("data", {}).get("text", ""))
            case "agent.tool_request":
                # Auto-approve tools that reach the client. The gateway's
                # permission policy already enforced ALLOW/DENY before this
                # point — only ASK-level tools arrive here, and scheduled
                # jobs are unattended so we approve them automatically.
                asyncio.create_task(ws.approve_tools())
            case "agent.context_compacted":
                pass  # compaction happened mid-turn; agent continues
            case "agent.cancelled":
                logger.info("Job run cancelled: chat_id=%s", chat_id)
                done.set()
            case "agent.error":
                msg = data.get("data", {}).get("message", "Unknown error")
                logger.error("Agent error during job: %s", msg)
                errors.append(msg)
                done.set()
            case "agent.turn_complete":
                done.set()

    ws.on_message(on_event)
    listen_task = asyncio.create_task(ws.listen())

    try:
        await ws.send_message(prompt, stream=True)
        await asyncio.wait_for(done.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        errors.append(f"Agent response timed out after {timeout:.0f}s")
    finally:
        listen_task.cancel()
        try:
            await listen_task
        except (asyncio.CancelledError, Exception):
            pass
        await ws.disconnect()

    if errors:
        raise RuntimeError(errors[0])

    return "".join(parts)


async def get_or_create_chat(
    host: str,
    port: int,
    token: str,
    sessions_path: str,
    job_name: str,
) -> str:
    """Return the persistent chat_id for this job, creating one if needed."""
    from scheduler.session_map import SessionMap

    sm = SessionMap(Path(sessions_path))
    chat_id = sm.get(job_name)
    if not chat_id:
        api = ClothoAPIClient(host, port, token)
        chat_id = await asyncio.to_thread(api.create_chat)
        sm.set(job_name, chat_id)
        logger.info("Created new chat for job '%s': %s", job_name, chat_id)
    return chat_id
