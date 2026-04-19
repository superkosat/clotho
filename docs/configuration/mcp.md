# MCP Servers

Clotho connects to external [Model Context Protocol](https://modelcontextprotocol.io) servers at gateway startup, making their tools available to every agent session alongside the built-in `bash`, `read`, `write`, and `edit` tools.

## Configuration

Add servers under `"mcp"` in `~/.clotho/config.json`:

```json
{
  "mcp": {
    "servers": {
      "filesystem": {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
      },
      "github": {
        "transport": "streamable_http",
        "url": "https://api.githubcopilot.com/mcp/",
        "auth": {
          "type": "token",
          "token_env": "GITHUB_TOKEN"
        }
      }
    }
  }
}
```

## Tool Namespacing

Each server's tools are prefixed with the server's config key. A tool named `list_directory` on the `filesystem` server becomes `filesystem__list_directory`. This prevents collisions between servers and with built-in tools.

Control the prefix with `tool_prefix`:

```json
"tool_prefix": "fs"    // custom prefix → fs__list_directory
"tool_prefix": ""      // disable prefix → list_directory
```

## Transports

### stdio

Spawns a local subprocess:

| Field | Required | Description |
|---|---|---|
| `transport` | yes | `"stdio"` |
| `command` | yes | Executable (e.g. `npx`, `python`) |
| `args` | no | Arguments passed to the process |
| `env` | no | Extra environment variables |

### streamable_http

Connects to a remote HTTP server:

| Field | Required | Description |
|---|---|---|
| `transport` | yes | `"streamable_http"` |
| `url` | yes | Server endpoint URL |
| `auth` | no | Auth config (see below) |

## Authentication

### No auth

Omit `auth` entirely. Suitable for local stdio servers.

### Static token

Reads a bearer token from an environment variable:

```json
"auth": {
  "type": "token",
  "token_env": "GITHUB_TOKEN"
}
```

Set the variable before starting Clotho:

```bash
export GITHUB_TOKEN="ghp_..."
clotho
```

### OAuth

Full Authorization Code flow with PKCE. Requires interactive authorization before first use.

```json
"auth": {
  "type": "oauth",
  "scopes": ["tools:read", "tools:execute"]
}
```

!!! warning "Headless gateway"
    The gateway cannot run a browser-based OAuth flow at startup. OAuth servers require stored credentials from a prior `/mcp auth` session. Servers with missing or expired tokens are skipped gracefully.

Authorize once from the REPL:

```
/mcp auth <server>
```

This opens a browser, completes the OAuth flow, and stores tokens in `~/.clotho/mcp/tokens/<server>.json`. Tokens are reused on subsequent gateway starts and refreshed automatically.

## REPL Commands

| Command | Description |
|---|---|
| `/mcp` | List configured MCP servers |
| `/mcp auth <server>` | Authorize an OAuth server interactively |

## Server Options

| Field | Default | Description |
|---|---|---|
| `enabled` | `true` | Set `false` to skip without removing the entry |
| `tool_prefix` | server key | Prefix for tool names (`""` to disable) |

If a server fails to connect at startup, Clotho logs the error and continues — other servers and built-in tools are unaffected.
