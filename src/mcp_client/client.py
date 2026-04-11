from __future__ import annotations

import logging
import os
import shutil
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Tool as MCPTool

from mcp_client.config import MCPServerConfig

logger = logging.getLogger(__name__)


class MCPClient:
    """Connection to a single MCP server (stdio transport, Phase 1)."""

    def __init__(self, config: MCPServerConfig):
        self._config = config
        self._session: ClientSession | None = None
        self._exit_stack = AsyncExitStack()
        self._tools: list[MCPTool] = []

    @staticmethod
    def _resolve_command(command: str, args: list[str]) -> tuple[str, list[str]]:
        """On Windows, only native .exe files can be exec'd directly by
        asyncio.create_subprocess_exec.  .cmd/.bat wrappers (npx, node, etc.)
        and unresolved commands must go through cmd.exe /c."""
        if sys.platform != "win32":
            return command, args
        resolved = shutil.which(command)
        if resolved and resolved.lower().endswith(".exe"):
            return command, args
        # Covers: .cmd, .bat, .ps1, not-found — all need the shell
        logger.debug("Routing '%s' through cmd.exe /c (resolved: %s)", command, resolved)
        return "cmd", ["/c", command, *args]

    async def connect(self) -> None:
        if self._config.transport != "stdio":
            raise ValueError(
                f"MCP server '{self._config.name}': only stdio transport is supported "
                f"in Phase 1, got {self._config.transport!r}"
            )
        if not self._config.command:
            raise ValueError(
                f"MCP server '{self._config.name}': stdio transport requires 'command'"
            )

        env = {**os.environ, **self._config.env} if self._config.env else None

        command, args = self._resolve_command(self._config.command, self._config.args)

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

        result = await self._session.list_tools()
        self._tools = result.tools
        logger.info(
            "MCP server '%s' connected with %d tool(s): %s",
            self._config.name,
            len(self._tools),
            [t.name for t in self._tools],
        )

    async def disconnect(self) -> None:
        await self._exit_stack.aclose()
        self._session = None
        self._tools = []
        logger.info("MCP server '%s' disconnected", self._config.name)

    async def call_tool(self, name: str, arguments: dict) -> str:
        if not self._session:
            raise RuntimeError(f"MCP server '{self._config.name}' is not connected")

        result = await self._session.call_tool(name, arguments)

        # Serialize all content blocks to text
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
