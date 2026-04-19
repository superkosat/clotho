# Permissions

Clotho's permission system controls whether tool calls are executed automatically or require approval.

## Modes

| Mode | Behaviour |
|---|---|
| `interactive` | Asks for approval before every tool call (default) |
| `autonomous` | Auto-approves all tools |
| `readonly` | Denies all tools except `read` |

Set the active mode:

```
/permission mode autonomous
```

## Per-Tool Overrides

Overrides take precedence over the active mode:

```
/permission set filesystem__write_file deny
/permission set bash allow
/permission clear bash
```

Levels: `allow`, `ask`, `deny`.

## REPL Commands

| Command | Description |
|---|---|
| `/permissions` | Show current mode and overrides |
| `/permission mode <mode>` | Set global mode |
| `/permission set <tool> <level>` | Override a specific tool |
| `/permission clear <tool>` | Remove an override |

## Config

Permissions are stored in `~/.clotho/config.json`:

```json
{
  "permissions": {
    "mode": "interactive",
    "tool_overrides": {
      "filesystem__write_file": "deny",
      "bash": "allow"
    }
  }
}
```

## Important Note

Since Clotho relies heavily on filesystem read access to understand its environment, and read critical files in `~/.clotho/workspace`, it is recommended to set a tool override for `"read": "allow"` if using interactive mode or readonly permissions mode. This allows for a more seamless user experience, without approval fatigue.
