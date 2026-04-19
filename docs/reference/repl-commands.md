# REPL Commands

All commands start with `/`. Type `/help` in the REPL to list them.

## Model Profiles

| Command | Description |
|---|---|
| `/profiles` | List all profiles |
| `/profile add` | Add a new profile (interactive) |
| `/profile use <name>` | Switch profile for this session |
| `/profile default <name>` | Set default profile for new sessions |

## Chats

| Command | Description |
|---|---|
| `/chats` | List all saved chat sessions |
| `/chat new` | Create and switch to a new chat |
| `/chat <id>` | Resume an existing chat |

## Permissions

| Command | Description |
|---|---|
| `/permissions` | Show current mode and overrides |
| `/permission mode <mode>` | Set mode: `interactive`, `autonomous`, `readonly` |
| `/permission set <tool> <level>` | Override a tool: `allow`, `ask`, `deny` |
| `/permission clear <tool>` | Remove a tool override |

## Streaming

| Command | Description |
|---|---|
| `/stream` | Show streaming status |
| `/stream on` / `/stream off` | Toggle streaming |

## Context

| Command | Description |
|---|---|
| `/context` | Show context window usage |
| `/compact` | Summarize old turns to free context space |

## Sandbox

| Command | Description |
|---|---|
| `/sandbox` | Show sandbox status |
| `/sandbox on` / `/sandbox off` | Enable or disable sandboxing |
| `/sandbox build` | Build the Docker sandbox image |

## MCP

| Command | Description |
|---|---|
| `/mcp` | List configured MCP servers |
| `/mcp auth <server>` | Authorize an OAuth MCP server |

## Other

| Command | Description |
|---|---|
| `/setup` | Configure a messaging channel (Discord, ...) |
| `/help` | Show all commands |
| `/exit` | Exit Clotho |
