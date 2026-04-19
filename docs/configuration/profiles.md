# Providers & Profiles

Model profiles map a name to a provider, model, and optional credentials. You can define multiple profiles and switch between them per session.

## Supported Providers

| Provider | Value | Notes |
|---|---|---|
| Anthropic | `anthropic` | Requires `api_key` |
| OpenAI (or compatible) | `openai` | Requires `api_key`; set `base_url` for local endpoints |
| Ollama | `ollama` | Local inference; no key needed |

## REPL Commands

| Command | Description |
|---|---|
| `/profiles` | List all profiles |
| `/profile add` | Add a new profile (interactive wizard) |
| `/profile use <name>` | Switch profile for this session |
| `/profile default <name>` | Set default profile for new sessions |

## Profile Fields

| Field | Required | Description |
|---|---|---|
| `provider` | yes | `anthropic`, `openai`, or `ollama` |
| `model` | yes | Model identifier (e.g. `claude-haiku-4-5-20251001`) |
| `base_url` | no | Override endpoint (useful for OpenAI-compatible servers) |
| `api_key` | no | API key (stored in `~/.clotho/profiles.json`) |
| `context_window` | no | Token limit; auto-filled for known models |
| `max_output_tokens` | no | Max tokens per response |

Profiles are stored in `~/.clotho/profiles.json`.
