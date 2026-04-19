# First Run

## Start the REPL

```bash
clotho
```

This starts the gateway in the background and opens the interactive REPL. The gateway runs on `127.0.0.1:8000` by default.

## Configure a Model Profile

Before chatting you need at least one model profile. Run `/profile add` and follow the prompts:

```
/profile add
Profile name: claude
Provider (openai/ollama/anthropic): anthropic
Model: claude-haiku-4-5-20251001
Base URL (optional):
API Key (optional): sk-ant-...

/profile default claude
```

Profiles are saved to `~/.clotho/profiles.json` and persist across sessions.

## Send Your First Message

Type any message and press Enter. The agent responds using the default profile.

```
> What files are in my current directory?
```

The agent has access to built-in tools — `bash`, `read`, `write`, and `edit` — and will ask for approval before running them (in the default `interactive` permission mode).

## Background Gateway

To keep the gateway running after closing the REPL:

```bash
clotho run -d
```

Reconnect later with `clotho` — it detects the running gateway and skips startup.
