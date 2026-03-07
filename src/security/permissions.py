import json
from pathlib import Path

from security.models import (
    PermissionLevel,
    PermissionsConfig,
    MODE_DEFAULTS,
)

CONFIG_DIR = Path.home() / ".clotho"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _read_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def load_permissions() -> PermissionsConfig:
    config = _read_config()
    raw = config.get("permissions", {})
    return PermissionsConfig(**raw)


def save_permissions(perms: PermissionsConfig) -> None:
    config = _read_config()
    config["permissions"] = perms.model_dump()
    _write_config(config)


def resolve_tool(tool_name: str, perms: PermissionsConfig) -> PermissionLevel:
    if tool_name in perms.tool_overrides:
        return perms.tool_overrides[tool_name]

    mode_map = MODE_DEFAULTS[perms.mode]
    if tool_name in mode_map:
        return mode_map[tool_name]

    return mode_map["__default__"]
