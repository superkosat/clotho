import asyncio
from datetime import datetime, timezone

from fastapi import WebSocket

from gateway.config import settings
from gateway.session import SessionState
from security.models import PermissionLevel
from security.permissions import load_permissions, resolve_tool


class AgentService:
    """
    WebSocket transport bridge. Provides emit/request_approval callbacks
    that ClothoController.run() uses to communicate with the client.
    """

    def __init__(self, session: SessionState, websocket: WebSocket):
        self.session = session
        self.ws = websocket

    async def handle_run(self, message: str, stream: bool = False):
        """Start an agent run. Spawned as a task so the receive loop stays free."""
        if self.session.run_lock.locked():
            await self._send_event("agent.error", {
                "code": "run_in_progress",
                "message": "A run is already active",
            })
            return

        async with self.session.run_lock:
            self.session.cancel_event.clear()
            try:
                await self.session.controller.run(
                    user_input=message,
                    emit=self._send_event,
                    request_approval=self._request_approval,
                    stream=stream,
                )
            except Exception as e:
                await self._send_event("agent.error", {
                    "code": "internal_error",
                    "message": str(e),
                })

    async def _send_event(self, event_type: str, data: dict):
        """emit callback — serialize and send over WebSocket."""
        await self.ws.send_json({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def _request_approval(self, tool_calls: list[dict]) -> dict[str, str]:
        """
        Per-tool permission evaluation. Returns a dict mapping each tool
        call ID to "allow" or "deny".

        - allow-level tools: approved immediately
        - deny-level tools: rejected immediately, client notified
        - ask-level tools: sent to client via WebSocket for approval
        """
        perms = load_permissions()
        verdicts: dict[str, str] = {}

        allow_calls = []
        ask_calls = []
        deny_calls = []

        for tc in tool_calls:
            level = resolve_tool(tc["name"], perms)
            if level == PermissionLevel.ALLOW:
                verdicts[tc["id"]] = "allow"
                allow_calls.append(tc)
            elif level == PermissionLevel.DENY:
                verdicts[tc["id"]] = "policy_deny"
                deny_calls.append(tc)
            else:
                ask_calls.append(tc)

        # Notify client about denied tools
        if deny_calls:
            denied_names = [tc["name"] for tc in deny_calls]
            await self._send_event("agent.tool_denied", {
                "tool_calls": deny_calls,
                "reason": f"Tools denied by permission policy: {denied_names}",
            })

        # If no tools need asking, we're done
        if not ask_calls:
            return verdicts

        # Send only ask-level tools to client for approval
        await self._send_event("agent.tool_request", {"tool_calls": ask_calls})

        loop = asyncio.get_event_loop()
        self.session.pending_approval = loop.create_future()

        try:
            result = await asyncio.wait_for(
                self.session.pending_approval,
                timeout=settings.approval_timeout_seconds,
            )
            approved = result.get("approved", False)
        except asyncio.TimeoutError:
            await self._send_event("agent.error", {
                "code": "approval_timeout",
                "message": "Tool approval timed out",
            })
            approved = False
        finally:
            self.session.pending_approval = None

        ask_verdict = "allow" if approved else "user_deny"
        for tc in ask_calls:
            verdicts[tc["id"]] = ask_verdict

        return verdicts

    def handle_tool_approval(self, data: dict):
        """Resolve the pending approval future when client responds."""
        if self.session.pending_approval and not self.session.pending_approval.done():
            self.session.pending_approval.set_result(data)

    def handle_cancel(self):
        """Signal cancellation — abort the run and reject any pending approval."""
        self.session.cancel_event.set()
        if self.session.pending_approval and not self.session.pending_approval.done():
            self.session.pending_approval.set_result({"approved": False})

    def handle_disconnect(self):
        """Client disconnected mid-run."""
        self.session.cancel_event.set()
        if self.session.pending_approval and not self.session.pending_approval.done():
            self.session.pending_approval.set_result({"approved": False})
