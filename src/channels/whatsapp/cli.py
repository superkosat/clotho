"""Entry point for the clotho-whatsapp bridge process."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="clotho-whatsapp",
        description=(
            "Clotho WhatsApp bridge — connects a running Clotho gateway to WhatsApp.\n\n"
            "On first run, a QR code will be printed to the terminal.\n"
            "Scan it with the WhatsApp mobile app to pair the bot.\n"
            "Subsequent runs reconnect automatically using the stored session."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default=str(Path.home() / ".clotho" / "whatsapp" / "config.toml"),
        metavar="PATH",
        help="Path to config.toml (default: ~/.clotho/whatsapp/config.toml)",
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
        help="Override auth token from config",
    )
    args = parser.parse_args()

    from channels.whatsapp.config import load_config
    from channels.whatsapp.bridge import WhatsAppBridge

    config = load_config(args.config)

    # CLI overrides
    if args.gateway_host:
        config.host = args.gateway_host
    if args.gateway_port:
        config.port = args.gateway_port
    if args.token:
        config.token = args.token

    if not config.token:
        print(
            "Error: no auth token found.\n"
            "Set [gateway] token in your config.toml, or run `clotho setup` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    bridge = WhatsAppBridge(config)

    print(f"[clotho-whatsapp] Connecting to gateway at {config.host}:{config.port}")
    print("[clotho-whatsapp] Scan the QR code below with WhatsApp (first run only).")

    try:
        asyncio.run(bridge.start())
    except KeyboardInterrupt:
        print("\n[clotho-whatsapp] Shutting down.")


if __name__ == "__main__":
    main()
