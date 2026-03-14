"""Configuration for the Clotho WhatsApp bridge."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".clotho" / "whatsapp" / "config.toml"
DEFAULT_DB_PATH = Path.home() / ".clotho" / "whatsapp" / "neonize.db"


@dataclass
class BridgeConfig:
    # Gateway connection
    host: str = "localhost"
    port: int = 8765
    token: str = ""

    # WhatsApp behaviour
    allowlist: list[str] = field(default_factory=list)
    tool_approval: str = "auto_allow"   # "auto_allow" | "auto_deny"
    chunk_limit: int = 4000
    denial_message: str = ""            # empty = silence unknown senders
    db_path: str = str(DEFAULT_DB_PATH)


def _load_gateway_token() -> str:
    """Fall back to the gateway token stored by `clotho setup`."""
    config_file = Path.home() / ".clotho" / "config.json"
    if config_file.is_file():
        import json
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
    wa = raw.get("whatsapp", {})

    token = gw.get("token") or _load_gateway_token()

    return BridgeConfig(
        host=gw.get("host", "localhost"),
        port=int(gw.get("port", 8765)),
        token=token,
        allowlist=wa.get("allowlist", []),
        tool_approval=wa.get("tool_approval", "auto_allow"),
        chunk_limit=int(wa.get("chunk_limit", 4000)),
        denial_message=wa.get("denial_message", ""),
        db_path=str(Path(wa.get("db_path", str(DEFAULT_DB_PATH))).expanduser()),
    )
