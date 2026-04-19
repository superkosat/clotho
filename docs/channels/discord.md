# Discord Bridge

Clotho can connect to Discord as a bot, letting you interact with the agent through DMs or server channels. The bridge is a standalone process that connects to a running gateway.

```bash
clotho run -d       # start gateway in background
clotho-discord      # connect to Discord
```

## Setup

### 1. Create a Discord Application

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application**, give it a name, click **Create**

### 2. Create the Bot User

1. In your application, click **Bot** in the left sidebar
2. Click **Add Bot** and confirm
3. Under **Privileged Gateway Intents**, enable **MESSAGE CONTENT INTENT**
4. Click **Save Changes**

### 3. Copy the Bot Token

On the **Bot** page, click **Reset Token**, confirm, then copy the token. Add it to your config (see below). Keep this token secret.

### 4. Invite the Bot

1. Go to **OAuth2 → URL Generator**
2. Under **Scopes**, check `bot`
3. Under **Bot Permissions**, check: Read Messages, Send Messages, Read Message History
4. Copy and open the generated URL, select your server, click **Authorize**

### 5. Get Server and Channel IDs

Enable Developer Mode in Discord (**User Settings → Advanced → Developer Mode**), then right-click your server or channel to copy IDs.

## Configuration

Create `~/.clotho/discord/config.toml`:

```toml
[gateway]
host = "localhost"
port = 8000
# token falls back to ~/.clotho/config.json if omitted

[discord]
bot_token = "..."               # required — from Developer Portal
session_mode = "user"           # "user" (per-user context) or "channel" (shared)
tool_approval = "auto_allow"    # "auto_allow" or "auto_deny"
mention_only = true             # require @mention in servers (DMs always respond)
chunk_limit = 1900
allowed_guild_ids = ["*"]       # ["*"] = all, [] = deny all, or specific IDs
allowed_channel_ids = ["*"]     # same format
stop_codeword = "!stop"         # cancel current session
stopall_codeword = "!stopall"   # cancel all sessions globally
```

## Session Modes

| Mode | Behaviour |
|---|---|
| `user` | Each Discord user gets their own persistent Clotho context |
| `channel` | Entire channel shares one context |

## Attachments

| Type | Extensions | Behaviour |
|---|---|---|
| Images | png, jpg, jpeg, gif, webp | Sent as base64 content blocks to the model |
| Audio | ogg, mp3, wav, m4a, flac | Saved to temp file; agent transcribes via whisper skill |
| Text/code | txt, md, csv, json, py, js, ... | Inlined as code blocks (up to 100 KB) |
| Binary | everything else | Noted with metadata; contents not included |

## Reactions

The agent can react to messages by including `{{react:emoji}}` directives in its response. The directive is stripped from the text and applied as a Discord reaction.
