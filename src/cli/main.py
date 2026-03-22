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


def _handle_setup(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="clotho setup")
    parser.add_argument("--force", action="store_true", help="Regenerate token even if one exists")
    parsed = parser.parse_args(args)

    from gateway.auth.setup import run_setup, generate_token, save_token
    if parsed.force:
        token = generate_token()
        save_token(token)
        print(f"Regenerated API token: {token}")
        print("Store this token securely. Clients use it to authenticate with the gateway.")
    else:
        run_setup()


def _handle_sandbox(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="clotho sandbox")
    subparsers = parser.add_subparsers(dest="sandbox_command")
    subparsers.add_parser("build", help="Build the sandbox Docker image")
    parsed = parser.parse_args(args)

    if parsed.sandbox_command == "build":
        from sandbox.build_image import build_sandbox_image
        success = build_sandbox_image()
        sys.exit(0 if success else 1)
    else:
        parser.print_help()


def _handle_run(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="clotho")
    parser.add_argument("-d", "--daemon", action="store_true", help="Run gateway in daemon mode (no CLI)")
    parser.add_argument("--host", default="127.0.0.1", help="Gateway host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Gateway port (default: 8000)")
    parser.add_argument("--chat", default=None, metavar="CHAT_ID", help="Resume an existing chat by ID")
    parser.add_argument("prompt", nargs="*", help="Initial prompt to send on startup")
    parsed = parser.parse_args(args)

    initial_prompt = " ".join(parsed.prompt) if parsed.prompt else None

    if parsed.daemon:
        from cli.daemon import run_daemon
        run_daemon(host=parsed.host, port=parsed.port)
    else:
        from cli.repl import run_repl
        run_repl(host=parsed.host, port=parsed.port, initial_prompt=initial_prompt, chat_id=parsed.chat)


def main():
    """Main entry point for the Clotho CLI."""
    setproctitle.setproctitle("clotho-cli")

    raw = sys.argv[1:]
    first = raw[0] if raw else None

    if first == "setup":
        _handle_setup(raw[1:])
    elif first == "sandbox":
        _handle_sandbox(raw[1:])
    else:
        # "run" is the default — strip the explicit keyword if present
        _handle_run(raw[1:] if first == "run" else raw)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.exit(handle_exception(exc))
