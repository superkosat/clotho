# Sandbox

When enabled, `bash` commands run inside a Docker container instead of your host system.

## Constraints

- Read-only root filesystem
- No network access
- 512 MB RAM / 1 CPU limit
- Workspace mounted at `/workspace`

## Setup

Docker must be running. Build the sandbox image once:

```bash
clotho sandbox build
# or from the REPL:
/sandbox build
```

## Enable / Disable

```
/sandbox on
/sandbox off
```

Or via config in `~/.clotho/config.json`:

```json
{
  "sandbox": {
    "enabled": true,
    "memory_limit": "512m",
    "cpu_quota": 100000,
    "timeout_seconds": 30,
    "network_enabled": false,
    "workspace_mode": "rw"
  }
}
```

Sandbox is disabled by default.
