"""Configuration for the Clotho scheduler."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".clotho" / "scheduler" / "config.toml"
DEFAULT_JOBS_DIR = Path.home() / ".clotho" / "jobs"
DEFAULT_JOB_STORE_PATH = Path.home() / ".clotho" / "scheduler" / "jobs.sqlite"


@dataclass
class SchedulerConfig:
    # Gateway connection
    host: str = "localhost"
    port: int = 8000
    token: str = ""

    # Job loading and APScheduler persistence
    jobs_dir: str = str(DEFAULT_JOBS_DIR)
    job_store_path: str = str(DEFAULT_JOB_STORE_PATH)

    # Delivery channel configs, keyed by channel type (e.g. "discord", "slack").
    # Each value is the raw dict from [delivery.<type>] in the TOML.
    # Channel-specific code is responsible for parsing its own subsection.
    delivery: dict[str, dict] = field(default_factory=dict)


def _load_gateway_token() -> str:
    """Fall back to gateway token stored by `clotho setup`."""
    config_file = Path.home() / ".clotho" / "config.json"
    if config_file.is_file():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            return data.get("api_token", "")
        except Exception:
            pass
    return ""


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> SchedulerConfig:
    """Load scheduler config from a TOML file.

    Example config (~/.clotho/scheduler/config.toml):

        [gateway]
        host = "localhost"
        port = 8000
        # token falls back to ~/.clotho/config.json if absent

        [scheduler]
        jobs_dir       = "~/.clotho/jobs"
        job_store_path = "~/.clotho/scheduler/jobs.sqlite"

        [delivery.discord]
        bot_token   = "..."
        chunk_limit = 1900

        # [delivery.slack]   <- future channels slot in here
        # webhook_url = "..."

    Missing file → defaults. Missing keys → per-field defaults.
    """
    p = Path(path).expanduser()
    raw: dict = {}
    if p.is_file():
        with p.open("rb") as f:
            raw = tomllib.load(f)

    gw = raw.get("gateway", {})
    sc = raw.get("scheduler", {})
    token = gw.get("token") or _load_gateway_token()

    return SchedulerConfig(
        host=gw.get("host", "localhost"),
        port=int(gw.get("port", 8000)),
        token=token,
        jobs_dir=sc.get("jobs_dir", str(DEFAULT_JOBS_DIR)),
        job_store_path=sc.get("job_store_path", str(DEFAULT_JOB_STORE_PATH)),
        delivery=raw.get("delivery", {}),
    )
