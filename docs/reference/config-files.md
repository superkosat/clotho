# Config Files

All configuration and persisted data lives in `~/.clotho/`.

| Path | Contents |
|---|---|
| `config.json` | Auth token, permissions, sandbox settings, MCP server definitions |
| `profiles.json` | Model profiles |
| `projects/*.jsonl` | Chat history (one file per session) |
| `skills/*/SKILL.md` | Skill definitions |
| `discord/config.toml` | Discord bridge configuration |
| `discord/sessions.json` | Discord user/channel → chat ID mapping |
| `jobs/*.yaml` | Scheduled job definitions |
| `scheduler/jobs.sqlite` | APScheduler job state |
| `mcp/tokens/*.json` | OAuth tokens for MCP servers (one per server) |
| `gateway.log` | Gateway process log (appended on each start) |

## config.json

Top-level keys:

```json
{
  "api_token": "clo_...",
  "permissions": {
    "mode": "interactive",
    "tool_overrides": {}
  },
  "sandbox": {
    "enabled": false,
    "memory_limit": "512m",
    "cpu_quota": 100000,
    "timeout_seconds": 30,
    "network_enabled": false,
    "workspace_mode": "rw"
  },
  "mcp": {
    "servers": {}
  }
}
```
