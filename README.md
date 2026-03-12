# Clotho

A terminal-based AI coding agent. Clotho runs a local gateway server that manages agent sessions, tool execution, and model routing. You can interact with it through a rich terminal REPL, or implement your own client.

## Installation

Requires Python 3.12+ and [pipx](https://pipx.pypa.io).

```bash
pipx install git+https://github.com/superkosat/clotho.git
clotho setup    # generate auth token
```

## First Run

```bash
clotho          # starts gateway + REPL
```

You'll need to configure a model profile before chatting:

```
/profile add
Profile name: anthropic
Provider: anthropic
Model: claude-haiku-4-5-20251001
API Key: sk-ant-...

/profile default anthropic
```

## REPL Commands

**Model profiles**
| Command | Description |
|---|---|
| `/profiles` | List all profiles |
| `/profile add` | Add a new profile (interactive) |
| `/profile use <name>` | Switch profile for this session |
| `/profile default <name>` | Set default profile for new sessions |

**Chats**
| Command | Description |
|---|---|
| `/chats` | List all saved chat sessions |
| `/chat new` | Create and switch to a new chat |
| `/chat <id>` | Resume an existing chat |

**Permissions**
| Command | Description |
|---|---|
| `/permissions` | Show current permission config |
| `/permission mode <mode>` | Set mode: `interactive`, `autonomous`, `readonly` |
| `/permission set <tool> <level>` | Override a tool: `allow`, `ask`, `deny` |
| `/permission clear <tool>` | Remove a tool override |

**Streaming**
| Command | Description |
|---|---|
| `/stream` | Show current streaming status |
| `/stream on` / `/stream off` | Toggle response streaming on or off |

Streaming is enabled by default. When on, responses render incrementally as tokens arrive. When off, the full response is delivered after the model finishes.

**Sandbox**
| Command | Description |
|---|---|
| `/sandbox` | Show sandbox status |
| `/sandbox on` / `/sandbox off` | Enable or disable sandboxing |
| `/sandbox build` | Build the Docker sandbox image |

## Providers

Clotho supports three providers via named profiles:

| Provider | Value |
|---|---|
| Anthropic | `anthropic` |
| OpenAI (or compatible) | `openai` |
| Ollama (local) | `ollama` |

Profiles are stored in `~/.clotho/profiles.json`.

## Permission Modes

- **interactive** (default) — asks for approval before every tool call
- **autonomous** — auto-approves all tools
- **readonly** — denies all tools except `read`

Per-tool overrides apply on top of the active mode.

## Sandbox

When enabled, bash commands run inside a Docker container with:
- Read-only root filesystem
- No network access
- 512MB RAM / 1 CPU limit
- Workspace mounted at `/workspace`

Docker must be running. Build the image once before enabling:

```bash
clotho sandbox build
```

Sandbox is disabled by default.

## Skills

Clotho will discover and load skill descriptions into the system prompt if they are located under `~/.clotho/skills/` with a `SKILL.md` file:

```
~/.clotho/skills/
    commit/
        SKILL.md
    review-pr/
        SKILL.md
```

`SKILL.md` starts with YAML frontmatter declaring the skill's name and description. The rest of the file contains instructions that the agent reads on demand when it determines the skill applies.

```markdown
---
name: commit
description: Stage and commit changes with a conventional commit message.
---

<instructions for the agent to follow>
```

Only the frontmatter metadata is injected into the system prompt. The full instructions stay on disk and are loaded by the agent when a skill matches the user's request.

## CLI Reference

```bash
clotho                  # start REPL (default)
clotho run              # same
clotho run -d           # start gateway as detached background process
clotho run --port 9000  # custom port
clotho setup            # generate auth token
clotho setup --force    # regenerate token
clotho sandbox build    # build Docker sandbox image
```

## Config Files

All config and persisted data lives in `~/.clotho/`:

| File | Contents |
|---|---|
| `config.json` | Permissions, sandbox settings, auth token |
| `profiles.json` | Model profiles |
| `projects/*.jsonl` | Chat history (one file per session) |
