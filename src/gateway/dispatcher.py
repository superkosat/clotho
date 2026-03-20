import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class EventPriority(IntEnum):
    """
    Integer priority levels for the gateway event dispatcher.

    Lower value = higher priority. Gaps are intentional — insert new levels
    between existing ones without renumbering (e.g. ELEVATED = 50, IDLE = 300).

    CRITICAL (0) events bypass the queue entirely via execute_critical().
    They cancel the current run and execute synchronously — they never queue.

    Any integer is valid; the dispatcher sorts by numeric value only.
    """
    CRITICAL   = 0    # stop, stopall — bypass queue, execute immediately
    NORMAL     = 100  # user messages, tool approvals
    BACKGROUND = 200  # hooks, heartbeats, scheduled jobs


@dataclass
class GatewayEvent:
    """Uniform event envelope used across all transports."""
    type: str
    data: dict
    priority: int
    source: str  # "websocket", "rest", "scheduler", "bridge"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(order=True)
class _QueueItem:
    """
    Internal priority queue entry. Ordered by (priority, seq) so that
    lower priority integers are dequeued first, with FIFO ordering within
    the same priority level.
    """
    priority: int
    seq: int
    handler: Callable[[], Awaitable[Any]] = field(compare=False)
    event: GatewayEvent = field(compare=False)


async def _noop() -> None:
    """Placeholder handler for evicted background events."""


class EventDispatcher:
    """
    Per-session priority event dispatcher.

    Run events are queued and processed sequentially in priority order by a
    background consumer task. Only one run executes at a time — the consumer
    awaits each handler to completion before dequeuing the next.

    Critical events (CRITICAL priority) bypass the queue entirely. Call
    execute_critical() for stop/stopall — it cancels the current run and
    executes synchronously without touching the queue.

    Background queue overflow: when the background lane reaches _BACKGROUND_LIMIT,
    the oldest background item is evicted (handler replaced with a no-op) to make
    room for the incoming one. This keeps the queue at the most recent events —
    useful for hooks and heartbeats that accumulate while the agent is busy.

    Priority is an integer — lower = higher priority. Three defaults are provided
    (CRITICAL=0, NORMAL=100, BACKGROUND=200), but any integer is accepted.
    New levels can be inserted between existing ones at any time without changing
    dispatch logic.

    Lifecycle: call start() to begin the consumer loop (requires a running event
    loop — call from async context). Call stop() to cancel everything cleanly.
    start() is idempotent; safe to call on reconnect.

    Future note: start() is currently called from the WebSocket handler. When the
    scheduler (hooks/heartbeat) is added, sessions with no active WebSocket will
    need their dispatcher started at session creation time.
    """

    _BACKGROUND_LIMIT: int = 10

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[_QueueItem] = asyncio.PriorityQueue()
        # Tracks queued background items in insertion order for oldest-eviction.
        self._background_items: deque[_QueueItem] = deque()
        self._seq: int = 0
        self._consumer_task: asyncio.Task | None = None
        self._current_run_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the consumer loop. Idempotent — safe to call on reconnect."""
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(
                self._consume(), name="dispatcher-consumer"
            )

    def stop(self) -> None:
        """Stop the consumer loop and cancel any in-progress or queued work."""
        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
        self.cancel_current()

    # ------------------------------------------------------------------
    # Event submission
    # ------------------------------------------------------------------

    def submit(
        self,
        event: GatewayEvent,
        handler: Callable[[], Awaitable[Any]],
    ) -> None:
        """
        Queue an event for sequential dispatch.

        CRITICAL events must not use this method — call execute_critical() instead.
        BACKGROUND events are subject to the _BACKGROUND_LIMIT cap; the oldest
        queued background item is evicted when the limit is reached.
        NORMAL events are queued unconditionally.
        """
        seq = self._seq
        self._seq += 1
        item = _QueueItem(priority=event.priority, seq=seq, handler=handler, event=event)

        if event.priority >= EventPriority.BACKGROUND:
            if len(self._background_items) >= self._BACKGROUND_LIMIT:
                oldest = self._background_items.popleft()
                logger.warning(
                    "Background queue at limit (%d); evicting oldest event type=%s",
                    self._BACKGROUND_LIMIT,
                    oldest.event.type,
                )
                # The oldest item is still in the asyncio queue — replace its
                # handler with a no-op so the consumer skips it when dequeued.
                oldest.handler = _noop  # type: ignore[assignment]
            self._background_items.append(item)

        self._queue.put_nowait(item)

    def execute_critical(self, handler: Callable[[], None]) -> None:
        """
        Execute a critical event immediately, bypassing the queue.

        Cancels the currently running task first, then calls handler()
        synchronously. Use for stop / stopall — never for events that
        should queue behind normal work.
        """
        self.cancel_current()
        handler()

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def cancel_current(self) -> None:
        """Cancel the currently executing run task, if any."""
        if self._current_run_task and not self._current_run_task.done():
            self._current_run_task.cancel()

    def drain(self) -> int:
        """
        Remove all pending (not yet started) items from the queue.
        Returns the number of items removed.
        """
        count = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                count += 1
            except asyncio.QueueEmpty:
                break
        self._background_items.clear()
        return count

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def queue_depth(self) -> int:
        """Total number of pending (not yet started) events."""
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        """True if a run task is currently executing."""
        return self._current_run_task is not None and not self._current_run_task.done()

    # ------------------------------------------------------------------
    # Consumer loop
    # ------------------------------------------------------------------

    async def _consume(self) -> None:
        """Dequeue and await handlers one at a time, in priority order."""
        while True:
            item = await self._queue.get()

            # Remove from background tracking (raises ValueError if already evicted).
            if item.event.priority >= EventPriority.BACKGROUND:
                try:
                    self._background_items.remove(item)
                except ValueError:
                    pass

            # Skip evicted background events — their handler was replaced with _noop.
            if item.handler is _noop:
                self._queue.task_done()
                continue

            self._current_run_task = asyncio.create_task(
                item.handler(), name=f"run-{item.event.type}"
            )
            try:
                await self._current_run_task
            except asyncio.CancelledError:
                logger.debug("Run task cancelled: type=%s", item.event.type)
            except Exception as e:
                logger.error("Run task raised unhandled exception: %s", e)
            finally:
                self._current_run_task = None
                self._queue.task_done()
