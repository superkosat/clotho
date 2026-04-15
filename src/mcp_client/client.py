from __future__ import annotations

import logging
import os
import shutil
import sys
from contextlib import AsyncExitStack

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.auth import OAuthClientProvider
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata
from mcp.types import Tool as MCPTool

from mcp_client.auth import (
    CallbackServer,
    FileTokenStorage,
    find_free_port,
    open_browser,
    port_from_redirect_uri,
)
from mcp_client.config import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPClient:
    """Connection to a single MCP server (stdio or streamable HTTP)."""

    def __init__(self, config: MCPServerConfig):
        self._config = config
        self._session: ClientSession | None = None
        self._exit_stack = AsyncExitStack()
        self._tools: list[MCPTool] = []

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        try:
            match self._config.transport:
                case "stdio":
                    await self._connect_stdio()
                case "streamable_http":
                    await self._connect_http()
                case other:
                    raise ValueError(
                        f"MCP server '{self._config.name}': unsupported transport {other!r}. "
                        f"Supported: 'stdio', 'streamable_http'."
                    )

            result = await self._session.list_tools()
            self._tools = result.tools
            logger.info(
                "MCP server '%s' connected with %d tool(s): %s",
                self._config.name,
                len(self._tools),
                [t.name for t in self._tools],
            )
        except BaseException:
            # Close anyio context managers in the same task that entered them.
            # Without this, the GC finalizes them in a different task context
            # and anyio raises "Attempted to exit cancel scope in a different task".
            await self._exit_stack.aclose()
            self._session = None
            self._tools = []
            raise

    async def disconnect(self) -> None:
        await self._exit_stack.aclose()
        self._session = None
        self._tools = []
        logger.info("MCP server '%s' disconnected", self._config.name)

    async def authorize(self) -> None:
        """Run the full interactive OAuth flow and persist tokens to disk.

        Unlike connect(), this does NOT require existing stored tokens — it
        is the command used to obtain them for the first time.  Opens the
        browser, waits for the callback, stores access + refresh tokens, then
        disconnects.  Call this via `/mcp auth <server>` in the REPL.
        """
        if self._config.transport != "streamable_http":
            raise ValueError(
                f"MCP server '{self._config.name}': OAuth only applies to streamable_http"
            )
        auth = self._config.auth or {}
        if auth.get("type") != "oauth":
            raise ValueError(
                f"MCP server '{self._config.name}' does not use OAuth auth"
            )

        storage = FileTokenStorage(self._config.name)
        storage.clear()  # start fresh so the provider runs the full flow

        port = find_free_port()
        redirect_uri = f"http://127.0.0.1:{port}/callback"

        callback_server = CallbackServer(port)
        await callback_server.start()

        scopes: list[str] = auth.get("scopes", [])
        client_metadata = OAuthClientMetadata(
            redirect_uris=[redirect_uri],  # type: ignore[arg-type]
            client_name=auth.get("client_name", "Clotho"),
            scope=" ".join(scopes) if scopes else None,
            grant_types=["authorization_code", "refresh_token"],
            token_endpoint_auth_method="none",
        )

        provider = OAuthClientProvider(
            server_url=self._config.url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=open_browser,
            callback_handler=callback_server.wait_for_callback,
            timeout=float(auth.get("timeout", 300)),
        )

        stack = AsyncExitStack()
        try:
            stack.push_async_callback(callback_server.stop)
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(auth=provider)
            )
            http_transport = await stack.enter_async_context(
                streamable_http_client(self._config.url, http_client=http_client)
            )
            read_stream, write_stream, _ = http_transport
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            logger.info(
                "OAuth authorization complete for MCP server '%s'", self._config.name
            )
        finally:
            await stack.aclose()

    async def call_tool(self, name: str, arguments: dict) -> str:
        if not self._session:
            raise RuntimeError(f"MCP server '{self._config.name}' is not connected")

        result = await self._session.call_tool(name, arguments)

        # Serialize all content blocks to text (multi-modal support deferred)
        parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts)

    @property
    def tools(self) -> list[MCPTool]:
        return list(self._tools)

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    # ------------------------------------------------------------------
    # Transport implementations
    # ------------------------------------------------------------------

    async def _connect_stdio(self) -> None:
        if not self._config.command:
            raise ValueError(
                f"MCP server '{self._config.name}': stdio transport requires 'command'"
            )

        env = {**os.environ, **self._config.env} if self._config.env else None

        command = self._config.command
        args = list(self._config.args)

        # On Windows, asyncio cannot exec .cmd/.bat scripts directly — they
        # are not PE executables.  shutil.which("npx") may return an
        # extensionless path that also cannot be exec'd, so probe for the
        # batch wrapper explicitly before falling back to the plain name.
        if sys.platform == "win32":
            candidates = (
                [command + ".cmd", command + ".bat", command]
                if not command.lower().endswith((".cmd", ".bat"))
                else [command]
            )
            resolved = None
            for candidate in candidates:
                r = shutil.which(candidate)
                if r and r.lower().endswith((".cmd", ".bat")):
                    resolved = r
                    break
            if resolved:
                args = ["/c", resolved] + args
                command = "cmd"

        params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
        )
        stdio_transport = await self._exit_stack.enter_async_context(stdio_client(params))
        read_stream, write_stream = stdio_transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

    async def _connect_http(self) -> None:
        if not self._config.url:
            raise ValueError(
                f"MCP server '{self._config.name}': streamable_http transport requires 'url'"
            )

        auth_type = (self._config.auth or {}).get("type")

        if auth_type == "oauth":
            await self._connect_http_oauth()
            return

        headers = self._build_token_headers()
        http_client = await self._exit_stack.enter_async_context(
            httpx.AsyncClient(headers=headers)
        )
        http_transport = await self._exit_stack.enter_async_context(
            streamable_http_client(self._config.url, http_client=http_client)
        )
        read_stream, write_stream, _ = http_transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

    async def _connect_http_oauth(self) -> None:
        """Connect using OAuth 2.1 Authorization Code flow with PKCE.

        Requires stored tokens to connect at gateway startup — the gateway runs
        as a headless subprocess and cannot block waiting for a browser.

        On first use (no tokens), raises ValueError so MCPManager skips this
        server gracefully.  Run `clotho mcp auth <server>` to authorize and
        store tokens; subsequent gateway restarts will connect automatically.

        With valid stored tokens the provider attaches the Bearer header with no
        user interaction.  On token expiry it attempts a silent refresh; if that
        also fails the server is unusable until re-authorized.
        """
        auth = self._config.auth or {}
        storage = FileTokenStorage(self._config.name)

        existing_tokens = await storage.get_tokens()
        existing_client = await storage.get_client_info()

        if not existing_tokens or not existing_client:
            raise ValueError(
                f"MCP server '{self._config.name}' requires OAuth authorization but no "
                f"stored credentials were found. Authorize first with: "
                f"clotho mcp auth {self._config.name}"
            )

        # Reuse the redirect URI port from the registered client so the callback
        # server is ready if a token refresh failure forces a full re-auth.
        port = port_from_redirect_uri(str(existing_client.redirect_uris[0]))
        if port is None:
            port = find_free_port()

        redirect_uri = f"http://127.0.0.1:{port}/callback"

        callback_server = CallbackServer(port)
        try:
            await callback_server.start()
        except OSError:
            port = find_free_port()
            redirect_uri = f"http://127.0.0.1:{port}/callback"
            callback_server = CallbackServer(port)
            await callback_server.start()

        await self._exit_stack.push_async_callback(callback_server.stop)

        scopes: list[str] = auth.get("scopes", [])
        client_metadata = OAuthClientMetadata(
            redirect_uris=[redirect_uri],  # type: ignore[arg-type]
            client_name=auth.get("client_name", "Clotho"),
            scope=" ".join(scopes) if scopes else None,
            grant_types=["authorization_code", "refresh_token"],
            token_endpoint_auth_method="none",  # public client
        )

        provider = OAuthClientProvider(
            server_url=self._config.url,
            client_metadata=client_metadata,
            storage=storage,
            redirect_handler=open_browser,
            callback_handler=callback_server.wait_for_callback,
            timeout=float(auth.get("timeout", 300)),
        )

        http_client = await self._exit_stack.enter_async_context(
            httpx.AsyncClient(auth=provider)
        )
        http_transport = await self._exit_stack.enter_async_context(
            streamable_http_client(self._config.url, http_client=http_client)
        )
        read_stream, write_stream, _ = http_transport
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _build_token_headers(self) -> dict[str, str]:
        """Build HTTP Authorization header for static token auth."""
        auth = self._config.auth
        if not auth:
            return {}

        match auth.get("type"):
            case "token":
                env_var = auth.get("token_env")
                if not env_var:
                    raise ValueError(
                        f"MCP server '{self._config.name}': "
                        f"'token' auth requires 'token_env'"
                    )
                token = os.environ.get(env_var)
                if not token:
                    raise ValueError(
                        f"MCP server '{self._config.name}': "
                        f"environment variable '{env_var}' is not set or empty"
                    )
                return {"Authorization": f"Bearer {token}"}

            case None:
                return {}

            case other:
                raise ValueError(
                    f"MCP server '{self._config.name}': unexpected auth type {other!r} "
                    f"in _build_token_headers (should have been handled earlier)"
                )
