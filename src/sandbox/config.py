"""Sandbox configuration management."""

import json
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / ".clotho"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_SANDBOX_CONFIG = {
    "enabled": False,  # Must opt-in for now
    "memory_limit": "512m",
    "cpu_quota": 100000,  # 1.0 CPU
    "timeout_seconds": 30,
    "network_enabled": False,
    "workspace_mode": "rw",
}


def _read_config() -> dict:
    """Read the entire config file."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config(config: dict) -> None:
    """Write the entire config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def load_sandbox_config() -> dict:
    """
    Load sandbox configuration from ~/.clotho/config.json.

    Returns:
        Sandbox config dict (merged with defaults)
    """
    config = _read_config()
    sandbox_config = config.get("sandbox", {})

    # Merge with defaults
    result = DEFAULT_SANDBOX_CONFIG.copy()
    result.update(sandbox_config)
    return result


def save_sandbox_config(sandbox_config: dict) -> None:
    """
    Save sandbox configuration to ~/.clotho/config.json.

    Preserves other config sections (permissions, api_token, etc.)

    Args:
        sandbox_config: Sandbox configuration to save
    """
    # Read existing config
    config = _read_config()

    # Update sandbox section
    config["sandbox"] = sandbox_config

    # Write back
    _write_config(config)


def is_sandbox_enabled() -> bool:
    """Check if sandboxing is enabled in config."""
    cfg = load_sandbox_config()
    return cfg.get("enabled", False)


def create_sandbox_from_config(
    session_id: str,
    workspace_path: Optional[str] = None,
) -> "Sandbox":
    """
    Create a Sandbox instance from config file settings.

    Args:
        session_id: Unique identifier for this sandbox
        workspace_path: Override workspace path

    Returns:
        Configured Sandbox instance
    """
    from sandbox.sandbox import Sandbox, SandboxConfig

    cfg = load_sandbox_config()

    sandbox_config = SandboxConfig(
        memory_limit=cfg["memory_limit"],
        cpu_quota=cfg["cpu_quota"],
        timeout_seconds=cfg["timeout_seconds"],
        network_enabled=cfg["network_enabled"],
        workspace_mode=cfg["workspace_mode"],
        workspace_path=workspace_path,
    )

    return Sandbox(config=sandbox_config, session_id=session_id)
