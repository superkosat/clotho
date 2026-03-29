"""ClothoScheduler — wraps APScheduler and dispatches jobs to registered delivery handlers."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scheduler.job import DeliveryTarget, JobDefinition, load_jobs
from scheduler.runner import get_or_create_chat, run_agent

logger = logging.getLogger(__name__)

DEFAULT_JOBS_DIR = Path.home() / ".clotho" / "jobs"
DEFAULT_JOB_STORE_PATH = Path.home() / ".clotho" / "scheduler" / "jobs.sqlite"
DEFAULT_SESSIONS_PATH = str(Path.home() / ".clotho" / "scheduler" / "sessions.json")

# ── Module-level delivery registry ────────────────────────────────────────────
#
# Keyed by delivery type string (e.g. "discord_dm", "discord_channel").
# Populated at startup by calling register_delivery_handler().
#
# Using a module-level dict means APScheduler can serialize job args as plain
# dicts (picklable), while handlers (callables) are resolved at runtime.
# New delivery channels register here without changing ClothoScheduler.

DeliveryHandler = Callable[[DeliveryTarget, str], Awaitable[None]]

_delivery_registry: dict[str, DeliveryHandler] = {}


def register_delivery_handler(delivery_type: str, handler: DeliveryHandler) -> None:
    """Register a delivery handler for a channel type.

    Called at bridge startup before the scheduler starts.  For example,
    the Discord bridge registers handlers for "discord_dm" and "discord_channel".
    """
    _delivery_registry[delivery_type] = handler
    logger.debug("Registered delivery handler for type '%s'", delivery_type)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _session_key_from_delivery(delivery: list[dict]) -> str | None:
    """Extract the session key from the first delivery target.

    The bridge's session map is keyed by channel_id (channel session mode) or
    user_id (user session mode).  Return whichever ID is present on the first
    delivery target, falling back to None if neither is found.
    """
    if not delivery:
        return None
    first = delivery[0]
    return first.get("channel_id") or first.get("user_id")


# ── Job execution function (module-level so APScheduler can serialize it) ─────

async def _execute_job(
    job_name: str,
    prompt: str,
    delivery: list[dict],   # serialized DeliveryTarget list
    gateway_host: str,
    gateway_port: int,
    gateway_token: str,
    sessions_path: str,
) -> None:
    """Run one job: get/create chat, call agent, deliver response to each target.

    Retry policy: attempt once; on failure retry once; on second failure log
    and send an error message to all delivery targets.
    """
    logger.info("Starting job '%s'", job_name)

    # Resolve persistent chat session for this job.
    # Use the first delivery target's identifier (channel_id or user_id) as the
    # session key — this matches the key the bridge uses in its session map, so
    # scheduled jobs share the same chat session as interactive messages.
    session_key = _session_key_from_delivery(delivery) or job_name
    try:
        chat_id = await get_or_create_chat(
            gateway_host, gateway_port, gateway_token, sessions_path, session_key
        )
    except Exception as exc:
        _log_and_deliver_error(job_name, delivery, gateway_host, gateway_port, gateway_token, sessions_path, f"Failed to get/create chat session: {exc}")
        return

    # Run agent with one retry
    response: str | None = None
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            response = await run_agent(
                gateway_host, gateway_port, gateway_token, chat_id, prompt
            )
            break
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                logger.warning("Job '%s' attempt 1 failed (%s), retrying…", job_name, exc)

    if response is None:
        await _deliver_error(
            job_name, delivery, f"Job failed after 2 attempts: {last_exc}"
        )
        return

    logger.info("Job '%s' complete (%d chars), delivering to %d target(s)", job_name, len(response), len(delivery))
    await _deliver(delivery, response)


def _log_and_deliver_error(
    job_name: str,
    delivery: list[dict],
    host: str,
    port: int,
    token: str,
    sessions_path: str,
    message: str,
) -> None:
    logger.error("Job '%s': %s", job_name, message)
    asyncio.create_task(_deliver_error(job_name, delivery, message))


async def _deliver(delivery: list[dict], content: str) -> None:
    for entry in delivery:
        dtype = entry.get("type", "")
        handler = _delivery_registry.get(dtype)
        if handler is None:
            logger.warning("No delivery handler registered for type '%s' — skipping", dtype)
            continue
        target = DeliveryTarget(type=dtype, params={k: v for k, v in entry.items() if k != "type"})
        try:
            await handler(target, content)
        except Exception as exc:
            logger.error("Delivery to '%s' failed: %s", dtype, exc)


async def _deliver_error(job_name: str, delivery: list[dict], message: str) -> None:
    logger.error("Job '%s' error: %s", job_name, message)
    error_text = f"⚠ Scheduled job **{job_name}** failed: {message}"
    await _deliver(delivery, error_text)


# ── Scheduler class ────────────────────────────────────────────────────────────

class ClothoScheduler:
    """Wraps APScheduler with Clotho job loading and delivery dispatch.

    Trigger types supported:
        cron     — standard 5-field cron expression via APScheduler CronTrigger
        (future) webhook, file_watch, gateway_event — add _register_<type> methods

    Delivery is handled by handlers registered via register_delivery_handler().
    """

    _RELOAD_INTERVAL: float = 30.0  # seconds between job directory re-scans

    def __init__(
        self,
        gateway_host: str,
        gateway_port: int,
        gateway_token: str,
        jobs_dir: str | Path = DEFAULT_JOBS_DIR,
        job_store_path: str | Path = DEFAULT_JOB_STORE_PATH,
        sessions_path: str = DEFAULT_SESSIONS_PATH,
    ) -> None:
        self._host = gateway_host
        self._port = gateway_port
        self._token = gateway_token
        self._jobs_dir = Path(jobs_dir).expanduser()
        self._sessions_path = sessions_path
        self._reload_task: asyncio.Task | None = None

        store_path = Path(job_store_path).expanduser()
        store_path.parent.mkdir(parents=True, exist_ok=True)

        self._scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{store_path}")},
            executors={"default": AsyncIOExecutor()},
        )

    def load_jobs(self) -> int:
        """Load all enabled jobs from jobs_dir. Returns count registered."""
        return self._sync_jobs()

    def _sync_jobs(self) -> int:
        """Synchronize APScheduler jobs with YAML files on disk.

        Adds new jobs, updates changed ones (via replace_existing), and removes
        jobs whose YAML files were deleted or disabled.  Returns the number of
        enabled jobs now registered.
        """
        jobs = load_jobs(self._jobs_dir)
        desired: dict[str, JobDefinition] = {}
        for job in jobs:
            if job.enabled:
                desired[job.name] = job

        # Register or update desired jobs
        count = 0
        for job in desired.values():
            try:
                self._register(job)
                count += 1
            except Exception as exc:
                logger.error("Failed to register job '%s': %s", job.name, exc)

        # Remove jobs that are no longer on disk or were disabled
        for existing in self._scheduler.get_jobs():
            if existing.id not in desired:
                logger.info("Removing job no longer on disk: %s", existing.id)
                existing.remove()

        return count

    def _register(self, job: JobDefinition) -> None:
        trigger_type = job.trigger.get("type")
        if trigger_type == "cron":
            self._register_cron(job)
        else:
            raise ValueError(f"Unknown trigger type: {trigger_type!r}")

    def _register_cron(self, job: JobDefinition) -> None:
        expression = job.trigger.get("expression", "")
        if not expression:
            raise ValueError("cron trigger requires an 'expression' field")

        # Serialize delivery targets as plain dicts for APScheduler pickling
        delivery_dicts = [
            {"type": t.type, **t.params} for t in job.delivery
        ]

        self._scheduler.add_job(
            _execute_job,
            CronTrigger.from_crontab(expression),
            args=[
                job.name,
                job.prompt,
                delivery_dicts,
                self._host,
                self._port,
                self._token,
                self._sessions_path,
            ],
            id=job.name,
            name=job.name,
            replace_existing=True,
            misfire_grace_time=3600,  # fire missed jobs up to 1 hour late on restart
            coalesce=True,            # collapse multiple missed fires into one
            max_instances=1,          # no concurrent runs of the same job
        )
        logger.info("Registered cron job: %s [%s]", job.name, expression)

    def start(self) -> None:
        self._scheduler.start()
        self._reload_task = asyncio.create_task(
            self._periodic_reload(), name="scheduler-reload"
        )
        logger.info("Scheduler started")

    def stop(self) -> None:
        if self._reload_task and not self._reload_task.done():
            self._reload_task.cancel()
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    async def _periodic_reload(self) -> None:
        """Re-scan the jobs directory periodically and sync with APScheduler."""
        while True:
            await asyncio.sleep(self._RELOAD_INTERVAL)
            try:
                self._sync_jobs()
            except Exception as exc:
                logger.error("Job reload failed: %s", exc)
