"""Configuration for the Clotho Discord bridge."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".clotho" / "discord" / "config.toml"


@dataclass
class BridgeConfig:
    # Gateway connection
    host: str = "localhost"
    port: int = 8000
    token: str = ""

    # Discord bot
    bot_token: str = ""
    session_mode: str = "user"           # "user" | "channel"
    tool_approval: str = "auto_allow"    # "auto_allow" | "auto_deny"
    chunk_limit: int = 1900
    mention_only: bool = True
    denial_message: str = ""             # empty = silence unknown senders
    allowed_guild_ids: list[str] = field(default_factory=list)    # str IDs or "*"
    allowed_channel_ids: list[str] = field(default_factory=list)  # str IDs or "*"


def _load_gateway_token() -> str:
    """Fall back to the gateway token stored by `clotho setup`."""
    config_file = Path.home() / ".clotho" / "config.json"
    if config_file.is_file():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            return data.get("api_token", "")
        except Exception:
            pass
    return ""


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> BridgeConfig:
    """Load bridge config from a TOML file.

    Missing file → returns defaults (token falls back to ~/.clotho/config.json).
    Missing keys → per-field defaults apply.
    """
    p = Path(path).expanduser()
    raw: dict = {}
    if p.is_file():
        with p.open("rb") as f:
            raw = tomllib.load(f)

    gw = raw.get("gateway", {})
    dc = raw.get("discord", {})

    token = gw.get("token") or _load_gateway_token()

    return BridgeConfig(
        host=gw.get("host", "localhost"),
        port=int(gw.get("port", 8000)),
        token=token,
        bot_token=dc.get("bot_token", ""),
        session_mode=dc.get("session_mode", "user"),
        tool_approval=dc.get("tool_approval", "auto_deny"),
        chunk_limit=int(dc.get("chunk_limit", 1900)),
        mention_only=bool(dc.get("mention_only", True)),
        denial_message=dc.get("denial_message", ""),
        allowed_guild_ids=[str(x) for x in dc.get("allowed_guild_ids", [])],
        allowed_channel_ids=[str(x) for x in dc.get("allowed_channel_ids", [])],
    )
