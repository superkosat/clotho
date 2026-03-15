"""Entry point for the clotho-discord bridge process."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="clotho-discord",
        description=(
            "Clotho Discord bridge — connects a running Clotho gateway to Discord.\n\n"
            "Requires a Discord bot token from the Developer Portal.\n"
            "See https://discord.com/developers/applications to create a bot."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=str(Path.home() / ".clotho" / "discord" / "config.toml"),
        metavar="PATH",
        help="Path to config.toml (default: ~/.clotho/discord/config.toml)",
    )
    parser.add_argument(
        "--gateway-host",
        metavar="HOST",
        help="Override gateway host from config",
    )
    parser.add_argument(
        "--gateway-port",
        type=int,
        metavar="PORT",
        help="Override gateway port from config",
    )
    parser.add_argument(
        "--token",
        metavar="TOKEN",
        help="Override Clotho gateway auth token from config",
    )
    parser.add_argument(
        "--bot-token",
        metavar="BOT_TOKEN",
        help="Override Discord bot token from config",
    )
    args = parser.parse_args()

    from channels.discord.config import load_config
    from channels.discord.bridge import DiscordBridge

    config = load_config(args.config)

    # CLI overrides
    if args.gateway_host:
        config.host = args.gateway_host
    if args.gateway_port:
        config.port = args.gateway_port
    if args.token:
        config.token = args.token
    if args.bot_token:
        config.bot_token = args.bot_token

    if not config.token:
        print(
            "Error: no Clotho gateway auth token found.\n"
            "Set [gateway] token in your config.toml, or run `clotho setup` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not config.bot_token:
        print(
            "Error: no Discord bot token found.\n"
            "Set [discord] bot_token in your config.toml.\n"
            "Create a bot at https://discord.com/developers/applications",
            file=sys.stderr,
        )
        sys.exit(1)

    bridge = DiscordBridge(config)

    print(f"[clotho-discord] Connecting to gateway at {config.host}:{config.port}")
    print("[clotho-discord] Starting Discord bot...")

    try:
        asyncio.run(bridge.start())
    except KeyboardInterrupt:
        print("\n[clotho-discord] Shutting down.")


if __name__ == "__main__":
    main()
