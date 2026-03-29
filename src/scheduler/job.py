"""Job definition — loaded from ~/.clotho/jobs/*.yaml."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class DeliveryTarget:
    """A single destination for a job's output.

    type:   delivery channel identifier — "discord_dm" | "discord_channel"
            Future channels add new type strings; the runner dispatches on this
            value so no changes to this class are needed.
    params: channel-specific parameters (user_id, channel_id, webhook_url, …).
            Kept as a raw dict so new channel types add fields without touching
            this dataclass.
    """
    type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobDefinition:
    """A single scheduled (or event-driven) agent job.

    trigger: dict describing how and when the job fires. Always has a "type" key.

        Cron (time-based):
            type: cron
            expression: "0 9 * * 1-5"   # standard 5-field cron

        Webhook (HTTP event, future):
            type: webhook
            path: /hooks/my-event        # path exposed by the scheduler HTTP server
            secret: "..."                # optional HMAC verification secret

        New trigger types slot in here without changing this dataclass or the YAML schema.

    delivery: list of DeliveryTarget — where to send the agent's response.
    """
    name: str
    trigger: dict[str, Any]
    prompt: str
    delivery: list[DeliveryTarget]
    enabled: bool = True


def load_jobs(jobs_dir: str | Path) -> list[JobDefinition]:
    """Load all *.yaml job files from jobs_dir. Skips files that fail to parse."""
    d = Path(jobs_dir).expanduser()
    if not d.is_dir():
        return []

    jobs: list[JobDefinition] = []
    for yaml_file in sorted(d.glob("*.yaml")):
        try:
            jobs.append(_load_job(yaml_file))
        except Exception as exc:
            print(f"[scheduler] Skipping {yaml_file.name}: {exc}", file=sys.stderr)
    return jobs


def _load_job(path: Path) -> JobDefinition:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    delivery: list[DeliveryTarget] = []
    for entry in raw.get("delivery", []):
        entry = dict(entry)
        dtype = entry.pop("type")
        delivery.append(DeliveryTarget(type=dtype, params=entry))

    return JobDefinition(
        name=raw["name"],
        trigger=raw["trigger"],
        prompt=raw["prompt"],
        delivery=delivery,
        enabled=bool(raw.get("enabled", True)),
    )
