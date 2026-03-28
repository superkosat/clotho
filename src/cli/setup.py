"""Interactive channel setup wizard for Clotho CLI."""

import asyncio
from pathlib import Path

from rich.console import Console
from rich.text import Text

from cli.picker import pick, PickerCancelled
from cli.theme import DIM, GREEN, PURPLE_BOLD, WARN_AMBER
from cli.ui import print_header, print_success, print_warning


# Registry of available channels: (value, display label)
_CHANNELS = [
    ("discord", "Discord  —  Chat bot for Discord servers and DMs"),
]


async def run_channel_setup(console: Console) -> None:
    """Show channel picker and dispatch to the appropriate setup wizard."""
    console.print()
    try:
        channel = await pick("Which channel would you like to set up?", _CHANNELS)
    except PickerCancelled:
        return

    if channel == "discord":
        await _setup_discord(console)


# ── Shared wizard helpers ──────────────────────────────────────────────────────

def _step(console: Console, n: int, title: str) -> None:
    t = Text()
    t.append(f"\n  ● Step {n} — ", style=f"bold {PURPLE_BOLD}")
    t.append(title, style=f"bold {PURPLE_BOLD}")
    console.print(t)


def _hint(console: Console, text: str) -> None:
    console.print(f"  [{DIM}]{text}[/{DIM}]")


async def _enter(console: Console, label: str = "Press Enter to continue → ") -> None:
    await asyncio.to_thread(console.input, f"  [{DIM}]{label}[/{DIM}]")


async def _prompt(console: Console, label: str) -> str:
    return await asyncio.to_thread(console.input, f"  {label}")


# ── Discord setup wizard ───────────────────────────────────────────────────────

async def _setup_discord(console: Console) -> None:
    console.print()
    print_header(console, "Discord Bridge Setup")
    console.print()
    _hint(console, "This wizard walks you through creating a Discord bot and writes")
    _hint(console, "~/.clotho/discord/config.toml so clotho-discord can connect.")
    console.print()

    step = 0

    def next_step(title: str) -> None:
        nonlocal step
        step += 1
        _step(console, step, title)

    # ── Step 1 ──────────────────────────────────────────────────────────────
    next_step("Create a Discord Application")
    console.print()
    _hint(console, "1. Go to  https://discord.com/developers/applications  in your browser")
    _hint(console, "2. Click  New Application  in the top-right corner")
    _hint(console, '3. Give it a name (e.g. "Clotho") and click  Create')
    console.print()
    await _enter(console)

    # ── Step 2 ──────────────────────────────────────────────────────────────
    next_step("Create the Bot user")
    console.print()
    _hint(console, "1. In your new application, click  Bot  in the left sidebar")
    _hint(console, "2. Click  Add Bot, then confirm with  Yes, do it!")
    console.print()
    await _enter(console)

    # ── Step 3 ──────────────────────────────────────────────────────────────
    next_step("Enable the Message Content Intent")
    console.print()
    _hint(console, "Without this, the bot cannot read message text — it will silently receive")
    _hint(console, "empty strings and never respond.")
    console.print()
    _hint(console, "1. Still on the  Bot  page, scroll to  Privileged Gateway Intents")
    _hint(console, "2. Toggle  MESSAGE CONTENT INTENT  to ON")
    _hint(console, "3. Click  Save Changes")
    console.print()
    await _enter(console)

    # ── Step 4 ──────────────────────────────────────────────────────────────
    next_step("Copy your bot token")
    console.print()
    _hint(console, "1. On the  Bot  page, under the TOKEN section, click  Reset Token")
    _hint(console, "2. Confirm, then click  Copy")
    _hint(console, "Keep this token secret — it is the bot's password. Never commit it to git.")
    _hint(console, "If it leaks, click  Reset Token  immediately to invalidate the old one.")
    console.print()

    bot_token = ""
    while not bot_token.strip():
        bot_token = await _prompt(console, "Paste bot token: ")
        if not bot_token.strip():
            print_warning(console, "  Bot token is required.")
    bot_token = bot_token.strip()

    # ── Step 5 ──────────────────────────────────────────────────────────────
    next_step("Invite the bot to your server")
    console.print()
    _hint(console, "1. In the left sidebar, go to  OAuth2 → URL Generator")
    _hint(console, "2. Under SCOPES, check:  bot")
    _hint(console, "3. Under BOT PERMISSIONS, check:")
    _hint(console, "     Read Messages / View Channels")
    _hint(console, "     Send Messages")
    _hint(console, "     Read Message History")
    _hint(console, "4. Copy the generated URL at the bottom of the page")
    _hint(console, "5. Paste it in your browser, select your server, click  Authorize")
    _hint(console, "   (You need  Manage Server  permission on that server)")
    console.print()
    await _enter(console)

    # ── Step 6 — Session mode ────────────────────────────────────────────────
    next_step("Session mode")
    console.print()
    _hint(console, "How should Clotho track conversation context?")
    console.print()
    try:
        session_mode = await pick(
            "Session mode",
            [
                ("user",    "Per user    — each Discord user has their own Clotho context (recommended)"),
                ("channel", "Per channel — everyone in a channel shares one context"),
            ],
        )
    except PickerCancelled:
        print_warning(console, "\n  Setup cancelled.")
        return

    # ── Step 7 — Server access ───────────────────────────────────────────────
    next_step("Server access")
    console.print()
    _hint(console, "The bot always responds to direct messages.")
    _hint(console, "For server channels, choose who can trigger it:")
    console.print()
    try:
        server_access = await pick(
            "Server access",
            [
                ("specific", "Specific servers/channels — allowlist by ID (most secure)"),
                ("all",      "All servers and channels the bot is in"),
                ("dms_only", "DMs only — ignore all server messages"),
            ],
        )
    except PickerCancelled:
        print_warning(console, "\n  Setup cancelled.")
        return

    allowed_guild_ids: list[str] = []
    allowed_channel_ids: list[str] = []
    mention_only = True

    if server_access == "all":
        allowed_guild_ids = ["*"]
        allowed_channel_ids = ["*"]

    elif server_access == "specific":
        console.print()
        _hint(console, "To find IDs: enable Developer Mode in User Settings → Advanced,")
        _hint(console, "then right-click a server icon → Copy Server ID,")
        _hint(console, "or right-click a channel → Copy Channel ID.")
        console.print()
        raw_guilds = await _prompt(console, "Guild/server IDs (comma-separated, or * for all): ")
        raw_channels = await _prompt(console, "Channel IDs (comma-separated, or * for all): ")
        allowed_guild_ids = [x.strip() for x in raw_guilds.split(",") if x.strip()] or ["*"]
        allowed_channel_ids = [x.strip() for x in raw_channels.split(",") if x.strip()] or ["*"]

    # dms_only → both lists stay empty (deny-all for servers)

    if server_access != "dms_only":
        # ── Step 8 — Trigger mode ────────────────────────────────────────────
        next_step("Trigger mode")
        console.print()
        _hint(console, "In server channels, when should the bot respond?")
        console.print()
        try:
            trigger = await pick(
                "Trigger mode",
                [
                    ("mention", "@mention only — respond only when explicitly @mentioned (recommended)"),
                    ("all",     "All messages  — respond to every message in allowed channels"),
                ],
            )
        except PickerCancelled:
            print_warning(console, "\n  Setup cancelled.")
            return
        mention_only = trigger == "mention"

    # ── Step (last) — Tool approval ──────────────────────────────────────────
    next_step("Tool approval")
    console.print()
    _hint(console, "When the agent needs to run a tool (bash, file edit, etc.),")
    _hint(console, "should it auto-approve or auto-deny calls coming from Discord?")
    console.print()
    try:
        tool_approval = await pick(
            "Tool approval",
            [
                ("auto_deny",  "Auto-deny   — agent requests permission but Discord users cannot approve (safer)"),
                ("auto_allow", "Auto-allow  — agent auto-approves all tool calls from Discord (powerful)"),
            ],
        )
    except PickerCancelled:
        print_warning(console, "\n  Setup cancelled.")
        return

    # ── Write config ─────────────────────────────────────────────────────────
    _write_discord_config(
        bot_token=bot_token,
        session_mode=session_mode,
        tool_approval=tool_approval,
        mention_only=mention_only,
        allowed_guild_ids=allowed_guild_ids,
        allowed_channel_ids=allowed_channel_ids,
    )

    console.print()
    print_success(console, "Config written to ~/.clotho/discord/config.toml")
    console.print()
    _hint(console, "Start the gateway, then run the bridge:")
    console.print()
    t = Text("  ")
    t.append("clotho-gateway &", style=f"bold {GREEN}")
    t.append("  &&  ", style=DIM)
    t.append("clotho-discord", style=f"bold {GREEN}")
    console.print(t)
    console.print()
    _hint(console, 'You should see:  [clotho-discord] Logged in as <BotName>#1234')
    console.print()


# ── Config writer ──────────────────────────────────────────────────────────────

def _toml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(f'"{v}"' for v in values) + "]"


def _write_discord_config(
    *,
    bot_token: str,
    session_mode: str,
    tool_approval: str,
    mention_only: bool,
    allowed_guild_ids: list[str],
    allowed_channel_ids: list[str],
) -> None:
    config_dir = Path.home() / ".clotho" / "discord"
    config_dir.mkdir(parents=True, exist_ok=True)

    content = f"""\
[gateway]
# host and port default to localhost:8000
# token falls back to ~/.clotho/config.json if absent

[discord]
bot_token           = "{bot_token}"
session_mode        = "{session_mode}"
tool_approval       = "{tool_approval}"
mention_only        = {"true" if mention_only else "false"}
allowed_guild_ids   = {_toml_list(allowed_guild_ids)}
allowed_channel_ids = {_toml_list(allowed_channel_ids)}
chunk_limit         = 1900
denial_message      = ""
stop_codeword       = "!stop"
stopall_codeword    = "!stopall"
"""
    (config_dir / "config.toml").write_text(content, encoding="utf-8")
