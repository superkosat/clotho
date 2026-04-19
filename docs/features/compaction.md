# Context Compaction

Long conversations are automatically compacted when the context window reaches 75% capacity. Old turns are summarized by the model while the most recent exchanges are preserved verbatim.

## Automatic Compaction

Triggered automatically when:

- The context window is configured (requires a known model or manually set `context_window`)
- Token usage exceeds 75% of the window
- There are more than 4 user turns in the conversation

Clotho emits an `agent.compaction_started` event during compaction and `agent.context_compacted` when done, with token counts before and after.

## Manual Compaction

```
/compact
```

Useful before switching to a smaller model or when you want to reset context size deliberately.

## Monitoring Usage

```
/context
```

Displays a visual bar showing current token usage, the 75% auto-compact threshold, and total window size.

## How It Works

1. Clotho counts tokens in the current context
2. If over threshold, the model is asked to summarize all but the last 4 user exchanges
3. The summary replaces the old turns; recent turns are kept verbatim
4. The compacted context is persisted to the chat file
