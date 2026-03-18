# Clotho Feature Roadmap — Architecture Analysis

## Current Architecture Summary

Clotho's runtime is three layers:

1. **Agent core** (`src/agent/`) — `ClothoController` manages conversation context (a list of `Turn` objects persisted as JSONL), invokes LLM providers through the `LLM` abstract interface, and runs a tool-use loop until the model stops requesting tools.
2. **Gateway** (`src/gateway/`) — FastAPI app with REST endpoints for session/profile/permission management and a WebSocket endpoint (`/ws/{chat_id}`) for real-time agent interaction. `AgentService` bridges WebSocket events to controller callbacks (`emit`, `request_approval`).
3. **Clients** — The CLI REPL, Discord bridge, and (future) other bridges connect to the gateway. Bridges are standalone processes that use `ClothoAPIClient` (REST) and `ClothoWebSocketClient` (WebSocket).

Key constraints relevant to the features below:
- The agent's `run()` method is a single `async` call that blocks until `turn_complete`. There is no mid-execution interrupt mechanism — `cancel_event` exists on `SessionState` but is never checked inside the run loop or streaming pipeline.
- `max_tokens` is hardcoded to 4000 in `core.py`. There is no context window tracking, no cumulative token accounting, and no `compact()` implementation in any provider.
- `ModelProfile` stores `provider`, `model`, `base_url`, `api_key` — no context window size or token limit metadata.
- The WebSocket protocol is event-driven and extensible — adding new event types requires no structural changes.

---

## Feature 1: Panic / Emergency Shutdown

### What it is
A signal (e.g., a codeword like `PANIC` or `!stop`) sent from any client (Discord, CLI, future bridges) that immediately halts the agent mid-execution — killing active tool calls, aborting LLM inference, and dropping back to idle.

### Why it matters
Today, cancellation only works at two narrow points: rejecting a pending tool approval future, or the WebSocket handler cancelling the `run_task` on disconnect. If the agent is mid-inference (blocked inside `stream_invoke` running in a thread) or mid-tool-execution (blocked inside `_execute_tool` running in a thread), there is no way to interrupt it. The user must wait for the current operation to finish.

### What needs to change

**Core changes required: Yes, but minimal.**

| Layer | Change | Scope |
|-------|--------|-------|
| **Gateway (WebSocket handler)** | Parse panic signal from incoming messages. On panic: cancel the `run_task` via `task.cancel()`, set `cancel_event`, reject pending approval. | Small — add a `case "panic"` to the match in `agent.py` |
| **Gateway (AgentService)** | Add `handle_panic()` that is more aggressive than `handle_cancel()` — sets a "hard stop" flag and cancels the run task. | Small |
| **Agent core (`run()`)** | Check `cancel_event` (or a passed cancellation token) at the top of each iteration of the tool-use `while` loop, before calling `invoke`/`stream_invoke`, and after returning from tool execution. Raise `CancelledError` or a custom `AgentCancelled` exception. | Medium — 4-5 checkpoint insertions in `run()` |
| **Agent core (`_stream_and_emit()`)** | Check cancellation between processing each delta from the queue. This is where the agent spends most wall-clock time during inference. | Small — add check in the `while True` loop |
| **Bridges (Discord, future)** | Parse the panic codeword from message text *before* forwarding to the agent. If matched, send `{"type": "panic"}` over WebSocket instead of `{"type": "run"}`. Must work even if a run is already in progress — bridges need to maintain the WebSocket connection across messages (currently Discord creates a new connection per message, which is a problem — see below). | Medium |
| **CLI REPL** | Already has Escape-to-cancel. Could add the same codeword, or a keybinding. | Small |

**Critical design issue: Discord bridge creates ephemeral WebSocket connections.** Each message creates a new `ClothoWebSocketClient`, sends a message, waits for completion, then disconnects. A panic signal sent as a *second* Discord message would create a *second* WebSocket connection — but the first connection (running the agent) is a different object. The panic must reach the *same session's* `run_task`.

**Solution options:**
1. **REST cancel endpoint** — Add `POST /api/chats/{chat_id}/cancel` to the gateway. Any client (including a second bridge connection) can hit this to cancel a running session. The gateway looks up the `SessionState` and cancels the run task directly. This is the cleanest approach — no need to maintain persistent WebSocket connections in bridges.
2. **Persistent WebSocket per session** — The bridge maintains one WebSocket connection per active session and can send cancel/panic events on it. More complex, changes the bridge architecture significantly.

**Recommendation:** Option 1 (REST cancel endpoint). It's simpler, works for all bridge types, and doesn't require architectural changes to bridges.

### Cost/Benefit
- **Cost:** Low-medium. ~5 files touched, mostly small additions. The REST cancel endpoint is the only new route.
- **Benefit:** High. Without this, a runaway agent (e.g., stuck in a tool loop, running a long bash command) cannot be stopped without killing the process.
- **Core logic changes:** Yes, but surgical — adding cancellation checkpoints to `run()` and `_stream_and_emit()`.

---

## Feature 2: Context Compaction

### What it is
When conversation context reaches ~90% of the active model's context window, automatically summarize older turns to free space — allowing indefinitely long conversations without hitting token limits or degraded output quality.

### Why it matters
Currently, context grows unbounded. The 20B Ollama model you tested hit its 4096-token ceiling on a single weather API response. Larger models will hit the same wall on longer conversations. There is no warning, no mitigation — the provider silently truncates or the model produces garbage.

### What needs to change

**Core changes required: Yes, significant.**

| Layer | Change | Scope |
|-------|--------|-------|
| **`ModelProfile`** | Add `context_window: int` field. Each profile must declare its model's context window size (e.g., 200000 for Claude, 128000 for GPT-4o, 4096 for small Ollama models). | Small |
| **`LLM` interface** | `compact()` needs a real signature: `compact(self, messages: list[Turn], target_tokens: int) -> list[Turn]`. It takes the current context and returns a compacted version that fits within `target_tokens`. | Small (interface change) |
| **Provider implementations** | Each provider implements `compact()`. The simplest approach: take the oldest N turns (excluding system turn and last K turns), format them as a "summarize this conversation" prompt, invoke the same model, replace those turns with a single `SystemTurn` or `UserTurn` containing the summary. All three providers need this. | Medium per provider × 3 |
| **Token counting** | Need a way to estimate token count of the current context *before* sending it to the model. Options: (a) use each provider's tokenizer (tiktoken for OpenAI, anthropic's token counting API, Ollama's token count from responses), (b) use a rough heuristic (chars ÷ 4), (c) track cumulative `input_tokens` from Usage and use the last value as an approximation. Option (c) is simplest but only works after the first invoke. | Medium |
| **Agent core (`run()`)** | Before each `invoke`/`stream_invoke` call, check if estimated context size ≥ 90% of `context_window`. If so, call `self.model.compact(self.context, target_tokens)` and replace `self.context` with the result. Emit a `agent.context_compacted` event so clients can display a notification. | Medium |
| **Profile switching guard** | When switching profiles (`SessionManager.switch_profile`), compare current context token estimate against the new model's `context_window`. If the current context exceeds the new model's window, either: (a) refuse the switch with an error, (b) force a compaction first, or (c) warn and proceed. Needs a policy decision. | Small-medium |
| **Persistence** | Compacted context must be saved. Currently each turn is appended to JSONL. After compaction, the JSONL file should be rewritten with the compacted turns (or a new compaction entry appended that replaces prior turns on load). | Medium |

**Design decisions needed:**
1. **What gets compacted?** Oldest turns first, preserving system prompt and the most recent N turns (e.g., last 3 exchanges). Tool results are often the largest — these should be aggressively summarized.
2. **Where does the summary go?** Either as a new `SystemTurn` ("Here is a summary of the conversation so far: ...") or as a replacement `UserTurn`. System turn is cleaner.
3. **Automatic vs. manual?** Automatic at 90% threshold, but also expose a manual `/compact` command for users who want to trigger it early.
4. **How to handle the compaction call itself consuming tokens?** The compaction prompt + old context must fit within the model's context window. If the context is already at 90%, there may not be enough room to include all old turns in the compaction prompt. Solution: compact in chunks — summarize the oldest 25% of turns first, then continue.

**Model switching policy recommendation:** Refuse the switch if current context exceeds the target model's window, with an error message suggesting the user compact first or stay on the current model. This is safer than silent truncation.

### Cost/Benefit
- **Cost:** Medium-high. Touches the core agent loop, all three providers, the profile system, and persistence. Most complex of the four features.
- **Benefit:** High. Without this, conversations have an invisible hard ceiling. The 20B model failure you just saw is the symptom. This also enables the hooks/heartbeat feature (Feature 3) to work over long time horizons without context exhaustion.
- **Core logic changes:** Yes, significant — new logic in `run()`, new `LLM` interface method, new profile field.

---

## Feature 3: Hooks / Heartbeat (Scheduled Agent Invocations)

### What it is
Cron-like scheduled jobs that invoke the agent proactively — e.g., "every day at 9am, fetch news and DM me on Discord." The agent wakes up, runs a predefined prompt, and sends the result to a configured channel (Discord DM, Discord channel, future bridges).

### Why it matters
Currently, the agent is purely reactive — it only acts when a user sends a message. Proactive invocations turn Clotho into a personal assistant that can deliver daily briefings, monitor systems, check stock prices, etc.

### What needs to change

**Core changes required: No.** The agent core doesn't need to change at all. Scheduled invocations are just automated messages sent to the gateway — the same flow as a Discord message or CLI input.

| Layer | Change | Scope |
|-------|--------|-------|
| **New component: Scheduler** | A new module (e.g., `src/scheduler/`) that: (a) loads job definitions from config, (b) runs a scheduling loop (using `asyncio` + time checks, or a library like `APScheduler`), (c) on trigger: calls `ClothoAPIClient.create_chat()` (or reuses a persistent chat), opens a WebSocket, sends the job's prompt, collects the response. | New module, medium |
| **Job config** | Jobs defined in a config file (e.g., `~/.clotho/hooks.toml` or `~/.clotho/jobs.toml`). Each job specifies: cron expression or interval, prompt text, delivery channel (discord DM to user ID, discord channel ID, etc.), chat persistence (new chat each time vs. reuse same chat). | New config format |
| **Delivery adapters** | The scheduler needs to deliver the agent's response to the right channel. For Discord: use the Discord bot client to send a DM or channel message. This means the scheduler either: (a) runs inside the Discord bridge process, or (b) runs as a separate process that connects to Discord independently, or (c) delivers via a webhook/REST call to the bridge. | Medium |
| **Gateway** | No changes needed — the scheduler is just another client connecting via the existing REST/WebSocket API. | None |
| **Agent core** | No changes needed — the agent doesn't know or care that the message came from a scheduled job. | None |

**Design decisions needed:**
1. **Where does the scheduler run?** Three options:
   - **Inside the gateway process** — simplest, but couples scheduling to the gateway lifecycle. If the gateway restarts, jobs are interrupted.
   - **Inside each bridge process** — the Discord bridge runs its own scheduler for Discord-targeted jobs. Keeps delivery simple (it already has the bot client). But jobs can't target multiple channels.
   - **Standalone process** — `clotho-scheduler` as a separate entry point. Most flexible, but needs its own Discord bot token or a delivery mechanism.

   **Recommendation:** Inside each bridge process. The Discord bridge already has a `discord.Client` and can send messages directly. Add a `Scheduler` that runs alongside the bridge's event loop. Jobs targeting Discord delivery are defined in the Discord bridge's config. Future bridges add their own schedulers. This avoids a new process and keeps delivery simple.

2. **Chat persistence for jobs** — Should a daily briefing reuse the same chat (building up context over time, e.g., "compare today's news to yesterday's") or start fresh each time (clean context, no accumulation)? Both are useful. Config should support `chat_mode = "persistent" | "ephemeral"`.

3. **Concurrent runs** — The gateway's `run_lock` prevents concurrent runs on the same session. If a user is chatting and a scheduled job fires for the same chat, the job should queue or use a different chat. Easiest: scheduled jobs always use their own dedicated chat IDs.

**OpenClaw reference:** The user mentioned researching OpenClaw's similar feature. This is worth doing during implementation for UX patterns (how they define schedules, how they handle failures/retries, how they report job results).

### Cost/Benefit
- **Cost:** Medium. New scheduler module, config format, and integration with bridge processes. But no core logic changes.
- **Benefit:** High. Transforms Clotho from reactive to proactive. Enables daily briefings, monitoring, alerts — the "personal assistant" use case.
- **Core logic changes:** None. The scheduler is a client-side concern.

---

## Feature 4: Interactive Bridge Setup

### What it is
A guided setup flow (e.g., `clotho setup discord`) that generates the `config.toml` file, walks the user through creating a Discord bot in the Developer Portal, and prompts them for the bot token — instead of requiring manual file creation and configuration.

### What needs to change

**Core changes required: No.**

| Layer | Change | Scope |
|-------|--------|-------|
| **CLI (`src/cli/main.py`)** | Add `setup` subcommands: `clotho setup discord`, `clotho setup whatsapp`, etc. Currently `clotho setup` only handles gateway token generation. | Small |
| **New setup modules** | `src/channels/discord/setup.py` — interactive flow that: (1) prints step-by-step instructions for creating a Discord bot, (2) prompts for bot token, (3) optionally prompts for guild/channel IDs, (4) generates `~/.clotho/discord/config.toml` with the gateway token auto-populated from `~/.clotho/config.json`, (5) validates the bot token by attempting a Discord API call. | Medium |
| **Config generation** | Template-based TOML generation with sensible defaults. The gateway `host`, `port`, and `token` can be auto-filled from the existing Clotho config. The user only needs to provide the Discord-specific values. | Small |
| **Validation** | After setup, optionally test the connection: (a) verify gateway is reachable, (b) verify Discord bot token is valid (make a lightweight Discord API call like "get current user"). | Small |

**Design decisions needed:**
1. **Interactive vs. one-shot?** Interactive is friendlier (step-by-step prompts with `input()`). But also support a non-interactive mode (`clotho setup discord --bot-token=xxx --guild-id=yyy`) for automation.
2. **Config location** — Currently hardcoded to `~/.clotho/discord/config.toml`. The setup flow should create the directory if needed and tell the user where the file was written.
3. **Re-running setup** — Should `clotho setup discord` overwrite an existing config? Safest: detect existing config, show current values, ask to overwrite or update specific fields.

### Cost/Benefit
- **Cost:** Low. No core changes. One new module per bridge type, minor CLI additions.
- **Benefit:** Medium. Reduces friction for new users. The current setup requires manually creating directories and TOML files, which is error-prone (you experienced this firsthand with port mismatches, missing tokens, etc.).
- **Core logic changes:** None.

---

## Feature 5: Gateway Event Dispatcher (Priority Queue)

### What it is
A central event ingestion and dispatch layer in the gateway that sits between client-facing transports (WebSocket, REST, future bridges) and the agent execution layer (`AgentService` / `ClothoController`). All inbound events — user messages, tool approvals, cancellations, panic signals, scheduled hook invocations — flow through this dispatcher, which processes them according to priority lanes rather than raw arrival order.

### Why it matters
Today, event handling is ad-hoc and tightly coupled to the WebSocket handler. The `match event_type` block in `agent.py` directly calls `AgentService` methods with no intermediary. This creates several problems that compound as the system grows:

1. **No prioritization.** A panic signal enters the same `receive_json()` loop as a chat message. If the loop is blocked waiting for the next WebSocket frame while the agent is mid-inference, the panic can't preempt it. The `run_lock` treats all `run` events equally — a scheduled heartbeat and a user message have identical priority.

2. **No queuing.** When `run_lock` is held, a second `run` event returns an immediate error (`"run_in_progress"`). With hooks/heartbeat (Feature 3), this becomes a real problem: a scheduled job firing while the user is chatting gets silently dropped. The correct behavior is to queue the lower-priority event and process it when the current run completes.

3. **No cross-client coordination.** Multiple bridges (CLI, Discord, future channels) can target the same session. Currently, whichever WebSocket connection happens to hold `run_lock` wins; others get errors. There's no mechanism for a second client to queue an event that runs after the current operation, or for a high-priority client event to preempt a background task.

4. **Tight coupling to WebSocket transport.** Adding a new event type (e.g., `hook_trigger`, `file_watch`, `mcp_event`) requires modifying the WebSocket handler. The REST endpoints are completely separate code paths with no shared dispatch logic. Feature 1 (Panic) needs a REST cancel endpoint that must somehow reach the same session state as the WebSocket handler — this is already a sign that dispatch logic wants to be centralized.

### Architecture

Priority is an **integer** — lower value means higher priority. The system ships with three default levels but is designed for arbitrary granularity. New levels can be inserted between existing ones without changing any dispatch logic, since the queue sorts by numeric value.

```python
class EventPriority(IntEnum):
    """Default priority levels. Not exhaustive — any integer works."""
    CRITICAL   = 0    # panic, cancel — immediate, bypasses queue
    NORMAL     = 100  # user messages, tool approvals
    BACKGROUND = 200  # hooks, heartbeats, scheduled jobs
```

Using spaced integers (0, 100, 200) leaves room for future levels without renumbering. For example, an `ELEVATED = 50` for time-sensitive hooks or an `IDLE = 300` for housekeeping tasks can be added later. The dispatcher doesn't switch on named levels — it just compares integers. Any event with priority < some configurable `IMMEDIATE_THRESHOLD` (default: 1) bypasses the queue and is handled inline.

**Default lanes (initial implementation):**

| Lane | Priority | Events | Behavior |
|------|----------|--------|----------|
| **Critical** | 0 | `panic`, `cancel` | Processed immediately. Can interrupt a running agent (sets cancellation flags, cancels the `run_task`). Never queued — always executed on receipt. |
| **Normal** | 100 | `run` (user messages), `tool_approval` | FIFO within the same priority. If the agent is idle, processed immediately. If a run is active, `tool_approval` is delivered to the pending future; `run` events queue behind the current run. |
| **Background** | 200 | `hook_trigger`, `heartbeat`, future scheduled events | FIFO within the same priority. Yields to all lower-numbered priorities. If the agent is idle and no higher-priority events are pending, processed immediately. |

**Scope: per-session dispatchers, global operations via composition.**

Each `SessionState` gets its own `EventDispatcher` instance. This keeps priority logic simple — no cross-session contention, no global locking in the hot path.

Global operations like `!stopall` (kill all active sessions) live one layer up in `SessionManager`, not in the dispatcher. The flow:

1. `!stopall` arrives via any transport (REST, WebSocket, bridge codeword)
2. Gateway calls `SessionManager.panic_all()`
3. `panic_all()` iterates all active `SessionState` instances and submits a Critical `panic` event to each session's dispatcher
4. Each dispatcher handles it identically to a per-session `!stop` — cancellation flags, task cancellation, pending approval rejection

The dispatcher doesn't know or care whether a panic was targeted or part of a bulk operation. Global coordination is composition (call N dispatchers), not a separate mechanism. This keeps the dispatcher simple and avoids a second dispatch layer for "global" vs "session" events. `SessionManager` already owns the session registry — it's the natural place for cross-session operations.

### What needs to change

**Core changes required: No.** The dispatcher is a gateway-layer concern. `ClothoController.run()` doesn't need to know about event priority — it receives a message and runs. The dispatcher decides *when* and *whether* to call `run()`.

| Layer | Change | Scope |
|-------|--------|-------|
| **New: `src/gateway/dispatcher.py`** | `EventDispatcher` class with `submit(event, priority)` and an internal `asyncio.PriorityQueue`. A consumer loop dequeues events and calls the appropriate `AgentService` method. Critical events bypass the queue entirely (handled inline on submission). | New module, medium |
| **Gateway (`session.py`)** | `SessionState` owns an `EventDispatcher` instead of (or alongside) the raw `run_lock`. The dispatcher internally manages run serialization — `run_lock` is either absorbed into the dispatcher or kept as an implementation detail. | Small refactor |
| **Gateway (`agent.py` WebSocket handler)** | Instead of directly calling `service.handle_run()` / `service.handle_cancel()`, the handler submits events to `session.dispatcher.submit(event)`. The dispatcher determines priority based on event type. The handler becomes a thin transport adapter. | Small refactor |
| **Gateway (REST routes)** | The cancel endpoint (Feature 1) and any future REST-triggered events submit through the same dispatcher. This is why centralization matters — REST and WebSocket events go through one path. | Small |
| **Hooks/Heartbeat (Feature 3)** | The scheduler submits `hook_trigger` events to the dispatcher at Background priority. If the user is chatting, the hook waits. If idle, it runs immediately. No special coordination code needed — the priority lanes handle it. | Simplifies Feature 3 |

### Design decisions needed

1. **Queue implementation.** `asyncio.PriorityQueue` is the natural fit. Events are `(priority, sequence_number, event_data)` tuples — `sequence_number` ensures FIFO within the same priority. Critical events don't enter the queue at all; they're handled synchronously on `submit()`.

2. **Queue depth / backpressure.** Should the Normal and Background lanes have a maximum depth? For Normal, probably not (user events should never be dropped). For Background, a bounded queue (e.g., 10) with oldest-dropped semantics prevents a flood of hook events from accumulating during a long user conversation.

3. **Starvation prevention.** Strict priority means a constant stream of Normal events could starve Background indefinitely. Two options:
   - **Accept it.** If the user is actively chatting, it's correct that hooks wait. Hooks will run during natural pauses.
   - **Aging.** After N Normal events processed, promote one Background event to Normal priority. Only needed if hooks have time-sensitive delivery requirements.

   **Recommendation:** Accept it. Hooks are inherently deferrable. If a hook has hard timing requirements, it should be Critical priority (but this should be rare and explicitly configured).

4. **Event schema.** Formalize the event structure across all transports:
   ```python
   @dataclass
   class GatewayEvent:
       type: str              # "run", "cancel", "panic", "tool_approval", "hook_trigger"
       data: dict             # event-specific payload
       priority: EventPriority  # CRITICAL, NORMAL, BACKGROUND
       source: str            # "websocket", "rest", "scheduler", "bridge"
       timestamp: datetime
   ```
   This replaces the raw `dict` parsing in the WebSocket handler and gives every event a uniform shape regardless of how it entered the system.

5. **Dispatcher lifecycle.** The dispatcher's consumer loop starts when the `SessionState` is created and stops when the session is removed. It runs as a background `asyncio.Task` on the gateway's event loop.

### How this interacts with other features

| Feature | Without Dispatcher | With Dispatcher |
|---------|-------------------|-----------------|
| **Panic Shutdown** | Needs custom plumbing: REST endpoint must find the `SessionState`, cancel the `run_task`, set flags. Each transport handles cancel differently. | Panic is a Critical event submitted to the dispatcher. One code path handles it regardless of whether it came from WebSocket, REST, or a bridge. |
| **Context Compaction** | No interaction — compaction is triggered inside `run()`. | No interaction. Same. |
| **Hooks/Heartbeat** | Scheduler must handle contention with user messages itself: check `run_lock`, retry on failure, implement its own backoff. If user is chatting when hook fires, hook fails or blocks. | Scheduler submits `hook_trigger` at Background priority. Dispatcher queues it behind any active/pending user messages. Zero contention logic in the scheduler. |
| **Bridge Setup** | No interaction. | No interaction. |

### Cost/Benefit
- **Cost:** Medium. One new module (`dispatcher.py`), small refactors to `session.py` and `agent.py`. No core agent logic changes. The dispatcher is conceptually simple — it's a priority queue with a consumer loop.
- **Benefit:** High. Provides the coordination substrate that Features 1, 3, and future extensibility all need. Without it, each feature implements its own ad-hoc event handling, and the gateway accumulates accidental complexity. With it, new event types (file watches, MCP events, inter-agent messages) slot in by defining a priority and a handler — no structural changes needed.
- **Core logic changes:** None. This is purely a gateway-layer concern.

### Risk
The main risk is premature abstraction — building a dispatcher before there are enough event types to justify it. However, Panic (Feature 1) and Hooks (Feature 3) are both planned, and both need exactly the coordination this provides. The dispatcher is small enough (~100-150 lines) that the abstraction cost is low relative to the coordination bugs it prevents.

---

## Implementation Priority Recommendation

| Priority | Feature | Rationale |
|----------|---------|-----------|
| **1** | Event Dispatcher | Foundational. Provides the coordination substrate that Panic and Hooks both need. Small scope (~150 lines), no core logic changes, but dramatically simplifies the implementation of Features 2 and 5. Building Panic without the dispatcher means writing ad-hoc plumbing that gets replaced later. Build the dispatcher first, then Panic becomes trivial. |
| **2** | Panic/Emergency Shutdown | Safety feature. With the dispatcher in place, this is just: (a) define `panic` as a Critical event, (b) add cancellation checkpoints in `run()` and `_stream_and_emit()`. The dispatcher handles the routing; the agent core handles the stopping. |
| **3** | Context Compaction | Correctness feature. Without it, every conversation has an invisible ceiling. The Ollama 4K failure you saw will happen to every model eventually. Must be in place before hooks/heartbeat (Feature 5), because scheduled jobs over days/weeks will exhaust context. |
| **4** | Interactive Bridge Setup | Quality-of-life. Low cost, reduces setup friction. Good to do before adding more bridges. |
| **5** | Hooks/Heartbeat | Most ambitious in scope but lowest urgency. Depends on context compaction being solid (long-running persistent chats). With the dispatcher in place, the scheduler just submits Background-priority events — zero contention logic needed. |

---

## Core Logic Impact Summary

| Feature | Agent Core | Gateway | Providers | Bridges | New Modules |
|---------|-----------|---------|-----------|---------|-------------|
| Event Dispatcher | None | Refactor `agent.py` handler to submit events; `SessionState` owns dispatcher | None | None | `src/gateway/dispatcher.py` |
| Panic Shutdown | Cancellation checkpoints in `run()` and `_stream_and_emit()` | Critical event type in dispatcher | None | Panic codeword parsing | None |
| Context Compaction | Pre-invoke size check, compaction trigger | Profile switching guard | `compact()` implementation × 3 | None | None |
| Hooks/Heartbeat | None | None | None | Scheduler integration | `src/scheduler/` |
| Bridge Setup | None | None | None | None | `src/channels/*/setup.py`, CLI subcommands |
