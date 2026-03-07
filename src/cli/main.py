"""Main entry point for Clotho CLI."""

import argparse
import sys

import setproctitle

from exceptions import ClothoException, ServiceException, SystemException


def handle_exception(exc: Exception) -> int:
    """Handle exceptions and return appropriate exit code.

    Returns:
        Exit code (0 for handled service errors, non-zero for system errors)
    """
    if isinstance(exc, SystemException):
        print(f"Error: {exc.message}", file=sys.stderr)
        return exc.exit_code
    elif isinstance(exc, ServiceException):
        print(f"Error: {exc.message}", file=sys.stderr)
        return 0  # Non-fatal, but we still exit since we're in main
    elif isinstance(exc, ClothoException):
        print(f"Error: {exc.message}", file=sys.stderr)
        return 1
    else:
        # Unexpected exception - show generic message
        print(f"Error: An unexpected error occurred. Please try again.", file=sys.stderr)
        return 1


def main():
    """Main entry point for the Clotho CLI."""
    setproctitle.setproctitle("clotho-cli")

    parser = argparse.ArgumentParser(
        prog="clotho",
        description="Clotho AI Coding Agent"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Generate authentication token")
    setup_parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate token even if one exists"
    )

    # Sandbox command
    sandbox_parser = subparsers.add_parser("sandbox", help="Sandbox management")
    sandbox_subparsers = sandbox_parser.add_subparsers(dest="sandbox_command")
    sandbox_subparsers.add_parser("build", help="Build the sandbox Docker image")

    # Run command (default behavior)
    run_parser = subparsers.add_parser("run", help="Start the CLI (default)")
    run_parser.add_argument(
        "-d", "--daemon",
        action="store_true",
        help="Run gateway in daemon mode (no CLI)"
    )
    run_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Gateway host (default: 127.0.0.1)"
    )
    run_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Gateway port (default: 8000)"
    )

    args = parser.parse_args()

    if args.command == "setup":
        from gateway.auth.setup import run_setup, generate_token, save_token
        if args.force:
            token = generate_token()
            save_token(token)
            print(f"Regenerated API token: {token}")
            print("Store this token securely. Clients use it to authenticate with the gateway.")
        else:
            run_setup()
    elif args.command == "sandbox":
        if args.sandbox_command == "build":
            from sandbox.build_image import build_sandbox_image
            success = build_sandbox_image()
            sys.exit(0 if success else 1)
        else:
            sandbox_parser.print_help()
    elif args.command == "run" or args.command is None:
        # Default to run if no command specified
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8000)
        daemon = getattr(args, "daemon", False)

        if daemon:
            from cli.daemon import run_daemon
            run_daemon(host=host, port=port)
        else:
            from cli.repl import run_repl
            run_repl(host=host, port=port)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.exit(handle_exception(exc))
