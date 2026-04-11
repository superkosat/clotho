from __future__ import annotations

import asyncio
import logging

from agent.models.tool import Tool
from mcp_client.config import MCPServerConfig, load_mcp_servers
from mcp_client.client import MCPClient
from mcp_client.tools import mcp_tool_to_clotho, make_prefixed_name

logger = logging.getLogger(__name__)


class MCPManager:
    """Manages connections to all configured MCP servers and exposes their tools."""

    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._tools: list[Tool] = []

    async def start(self) -> None:
        """Connect to all enabled servers defined in config.json."""
        configs = load_mcp_servers()
        if not configs:
            return

        for config in configs:
            if not config.enabled:
                logger.debug("MCP server '%s' is disabled, skipping", config.name)
                continue
            await self._connect_server(config)

    async def _connect_server(self, config: MCPServerConfig) -> None:
        client = MCPClient(config)
        try:
            await client.connect()
        except Exception as exc:
            logger.error(
                "Failed to connect to MCP server '%s': %s", config.name, exc
            )
            return

        # Check for name collisions before committing
        existing_names: set[str] = {t.name for t in self._tools}
        new_tools: list[Tool] = []
        collision = False

        loop = asyncio.get_running_loop()

        for mcp_tool in client.tools:
            prefixed = make_prefixed_name(config.name, mcp_tool.name, config.tool_prefix)
            if prefixed in existing_names:
                logger.error(
                    "MCP server '%s': tool name collision on '%s' — skipping this server",
                    config.name,
                    prefixed,
                )
                collision = True
                break
            existing_names.add(prefixed)

            raw_name = mcp_tool.name

            def _make_func(c: MCPClient = client, n: str = raw_name, l: asyncio.AbstractEventLoop = loop):
                def func(**kwargs) -> str:
                    future = asyncio.run_coroutine_threadsafe(c.call_tool(n, kwargs), l)
                    return future.result(timeout=60)
                return func

            new_tools.append(mcp_tool_to_clotho(mcp_tool, config, _make_func()))

        if collision:
            await client.disconnect()
            return

        self._clients[config.name] = client
        self._tools.extend(new_tools)
        logger.info(
            "Registered %d MCP tool(s) from server '%s'",
            len(new_tools),
            config.name,
        )

    async def stop(self) -> None:
        """Disconnect all servers."""
        for name, client in list(self._clients.items()):
            try:
                await client.disconnect()
            except Exception as exc:
                logger.warning("Error disconnecting MCP server '%s': %s", name, exc)
        self._clients.clear()
        self._tools.clear()

    def get_tools(self) -> list[Tool]:
        """Return Clotho Tool objects for all connected MCP servers."""
        return list(self._tools)
