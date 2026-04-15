from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILE = Path.home() / ".clotho" / "config.json"


@dataclass
class MCPServerConfig:
    name: str
    transport: str                      # "stdio" | "streamable_http"
    command: str | None = None          # stdio: executable
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None              # http: endpoint URL
    auth: dict | None = None            # auth config: {"type": "token", "token_env": "VAR"} | oauth (phase 3)
    enabled: bool = True
    tool_prefix: str | None = None      # None = use server name; "" = no prefix
    # Stubbed — accepted in config, not yet implemented:
    resources: bool = False
    prompts: bool = False


def load_mcp_servers() -> list[MCPServerConfig]:
    """Load MCP server configs from ~/.clotho/config.json under the 'mcp.servers' key."""
    if not CONFIG_FILE.exists():
        return []
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    servers_raw = raw.get("mcp", {}).get("servers", {})
    configs: list[MCPServerConfig] = []
    for name, cfg in servers_raw.items():
        configs.append(MCPServerConfig(
            name=name,
            transport=cfg.get("transport", "stdio"),
            command=cfg.get("command"),
            args=cfg.get("args", []),
            env=cfg.get("env", {}),
            url=cfg.get("url"),
            auth=cfg.get("auth"),
            enabled=cfg.get("enabled", True),
            tool_prefix=cfg.get("tool_prefix"),
            resources=cfg.get("resources", False),
            prompts=cfg.get("prompts", False),
        ))
    return configs
