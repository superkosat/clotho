# CLI Reference

## `clotho`

```
clotho [OPTIONS] [PROMPT]
```

| Flag | Description |
|---|---|
| `PROMPT` | Start REPL with an initial prompt |
| `-p "prompt"` | Print mode — send prompt, print response, exit |
| `--chat ID` | Resume an existing chat (print mode) |
| `--timeout N` | Timeout in seconds for print mode (default: 300) |

**Print mode** (`-p`) sends a single prompt and writes the raw response to stdout with no formatting — suitable for piping and scripts. Tool requests are auto-approved (gateway permission policy still applies).

```bash
clotho "what files are here?"          # REPL with initial prompt
clotho -p "summarise this repo"        # print mode
echo "what time is it" | clotho -p    # print mode from stdin
clotho -p "update deps" --chat abc123 # print mode into existing chat
clotho -p "run tests" --timeout 120
```

## `clotho run`

```
clotho run [OPTIONS]
```

| Flag | Description |
|---|---|
| `-d` | Start gateway as a detached background process |
| `--port N` | Custom port (default: 8000) |
| `--host HOST` | Custom host (default: 127.0.0.1) |

## `clotho setup`

```
clotho setup [--force]
```

Generates an auth token and writes it to `~/.clotho/config.json`. Use `--force` to regenerate an existing token.

## `clotho sandbox`

```
clotho sandbox build
```

Builds the Docker sandbox image (`clotho-sandbox:latest`). Required before enabling the sandbox.

## `clotho-discord`

```
clotho-discord [OPTIONS]
```

| Flag | Description |
|---|---|
| `--config PATH` | Config file path (default: `~/.clotho/discord/config.toml`) |
| `--gateway-host HOST` | Override gateway host |
| `--gateway-port PORT` | Override gateway port |
| `--token TOKEN` | Override gateway auth token |
| `--bot-token TOKEN` | Override Discord bot token |
