from __future__ import annotations

from typing import Callable

from mcp.types import Tool as MCPTool

from agent.models.tool import Tool
from mcp_client.config import MCPServerConfig


def make_prefixed_name(server_name: str, tool_name: str, tool_prefix: str | None) -> str:
    """Return the namespaced tool name used within Clotho's tool registry.

    tool_prefix=None  → use server_name as prefix  (e.g. "github__search_issues")
    tool_prefix=""    → no prefix                   (e.g. "search_issues")
    tool_prefix="gh"  → use custom prefix           (e.g. "gh__search_issues")
    """
    prefix = server_name if tool_prefix is None else tool_prefix
    return f"{prefix}__{tool_name}" if prefix else tool_name


def mcp_tool_to_clotho(
    mcp_tool: MCPTool,
    config: MCPServerConfig,
    func: Callable[..., str],
) -> Tool:
    """Convert an MCP tool definition to a Clotho Tool object."""
    return Tool(
        name=make_prefixed_name(config.name, mcp_tool.name, config.tool_prefix),
        description=mcp_tool.description or "",
        parameters=dict(mcp_tool.inputSchema) if mcp_tool.inputSchema else {
            "type": "object",
            "properties": {},
        },
        func=func,
    )
