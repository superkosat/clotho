"""Rich-based REPL for Clotho agent interaction."""

import asyncio
import sys

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from cli.animation import ParticleSpinner
from cli.api_client import ClothoAPIClient
from cli.commands import CommandHandler
from cli.gateway_manager import GatewayManager
from cli.input import CancelledInput, ClothoInput
from cli.theme import (
    CLOTHO_THEME,
    GREEN, GREEN_BOLD, PURPLE, PURPLE_BOLD,
    DIM, ERROR_RED, WARN_AMBER,
)
from cli.ws_client import ClothoWebSocketClient


class ClothoREPL:
    """Rich-based REPL for Clotho agent interaction."""

    def __init__(self, host: str, port: int, initial_prompt: str | None = None, chat_id: str | None = None):
        """Initialize REPL.

        Args:
            host: Gateway host address
            port: Gateway port number
            initial_prompt: Optional prompt to send automatically on startup
            chat_id: Optional existing chat ID to resume
        """
        self.console = Console(theme=CLOTHO_THEME)
        self.host = host
        self.port = port
        self.initial_prompt = initial_prompt
        self._requested_chat_id = chat_id
        self.token = None
        self.chat_id = None
        self.api_client = None
        self.ws_client = None
        self.command_handler = None
        self.running = True
        self.pending_approval = False
        self.spinner: ParticleSpinner | None = None
        self.rotating_phrases = False
        self.response_complete = asyncio.Event()
        self.active_profile = None
        self.streaming = True
        self._response_buffer = ""
        self._live: Live | None = None
        self._input = ClothoInput()
        self.loading_phrases = [
            "Thinking",
            "Processing",
            "Analyzing",
            "Working on it",
            "Computing",
            "Considering",
            "Pondering",
            "Cogitating",
            "Deliberating",
            "Reasoning",
        ]

    def setup(self):
        """Load token and create clients."""
        from gateway.auth.token import load_token

        self.token = load_token()
        if not self.token:
            self.console.print(f"[{ERROR_RED}]No auth token found. Run: clotho setup[/{ERROR_RED}]")
            sys.exit(1)

        # Create API client
        self.api_client = ClothoAPIClient(self.host, self.port, self.token)

        # Create command handler
        self.command_handler = CommandHandler(self.console, self.api_client)

    async def start_session(self):
        """Create or resume chat session."""
        if self._requested_chat_id:
            # Validate and resume existing chat
            chats = self.api_client.list_chats()
            chat_ids = [c["chat_id"] for c in chats]
            if self._requested_chat_id not in chat_ids:
                from exceptions import SystemException
                raise SystemException(
                    message=f"Chat not found: {self._requested_chat_id}",
                    exit_code=2
                )
            self.chat_id = self._requested_chat_id
        else:
            # Create new chat
            self.chat_id = self.api_client.create_chat()

        # Track the initial profile (set by default on session creation)
        try:
            self.active_profile = self.api_client.get_active_profile(self.chat_id)
        except Exception:
            pass

        # Connect WebSocket
        self.ws_client = ClothoWebSocketClient(
            self.host, self.port, self.chat_id, self.token
        )
        await self.ws_client.connect()
        self.ws_client.on_message(self.handle_message)

        # Start listening in background
        asyncio.create_task(self.ws_client.listen())

    async def rotate_loading_phrases(self):
        """Rotate through loading phrases while waiting for response."""
        phrase_index = 0
        while self.rotating_phrases and self.spinner:
            try:
                phrase = self.loading_phrases[phrase_index]
                self.spinner.update_label(phrase)
                phrase_index = (phrase_index + 1) % len(self.loading_phrases)
                await asyncio.sleep(1.5)
            except Exception:
                break

    def _stop_spinner(self):
        """Stop the particle spinner if active."""
        if self.spinner:
            self.rotating_phrases = False
            self.spinner.stop()
            self.spinner = None

    def _stop_live(self):
        """Stop the Live markdown display if active."""
        if self._live is not None:
            self._live.stop()
            self._live = None
        self._response_buffer = ""

    def handle_message(self, message: dict):
        """Handle incoming WebSocket message.

        Args:
            message: Message from server
        """
        msg_type = message.get("type")
        data = message.get("data", {})

        if msg_type in ("agent.text", "agent.text_delta"):
            # Stop loading animation when first text arrives
            self._stop_spinner()

            text = data.get("text", "")
            self._response_buffer += text

            # Start Live display on first chunk, then update
            if self._live is None:
                self._live = Live(Markdown(self._response_buffer), console=self.console, auto_refresh=False)
                self._live.start()
            else:
                self._live.update(Markdown(self._response_buffer), refresh=True)

        elif msg_type == "agent.tool_request":
            self._stop_spinner()
            self._stop_live()

            # Tool approval required - display all tools
            tool_calls = data.get("tool_calls", [])
            header = Text()
            header.append("\n  ", style="")
            header.append("⊹ ", style=PURPLE_BOLD)
            header.append(f"Tool approval required ", style=f"bold {PURPLE}")
            header.append(f"({len(tool_calls)} tool(s))", style=DIM)
            self.console.print(header)
            for tool in tool_calls:
                tool_name = tool.get("name", "unknown")
                tool_args = tool.get("arguments", {})
                line = Text()
                line.append("    ✦ ", style=PURPLE)
                line.append(tool_name, style=f"bold {PURPLE_BOLD}")
                line.append(f": {tool_args}", style=DIM)
                self.console.print(line)

            # Set pending approval flag and wake up the loop
            self.pending_approval = True
            self.response_complete.set()

        elif msg_type == "agent.tool_result":
            # Tool executed
            content = data.get("content", "")
            is_error = data.get("is_error", False)

            if is_error:
                self.console.print(f"[{ERROR_RED}]Tool error: {content}[/{ERROR_RED}]")
            else:
                # Truncate long results
                if len(content) > 500:
                    content = content[:500] + "... (truncated)"
                self.console.print(f"[{DIM}]Result: {content}[/{DIM}]")

        elif msg_type == "agent.error":
            self._stop_spinner()
            self._stop_live()
            error = data.get("message", "Unknown error")
            self.console.print(f"\n[{ERROR_RED}]Error: {error}[/{ERROR_RED}]")
            self.response_complete.set()

        elif msg_type == "agent.turn_complete":
            self._stop_spinner()

            # Stop Live markdown display
            if self._live is not None:
                self._live.stop()
                self._live = None
            self._response_buffer = ""

            stop_reason = data.get("stop_reason", "")
            model = data.get("model", "")
            done = Text()
            done.append("✦ Done", style=f"bold {GREEN}")
            done.append(f" ({model} - {stop_reason})", style=DIM)
            self.console.print(done)
            self.pending_approval = False
            self.response_complete.set()

        elif msg_type == "connection.error":
            self._stop_spinner()
            self._stop_live()
            error_msg = data.get("message", "Unknown connection error")
            self.console.print(f"\n[{ERROR_RED}]⊹ WebSocket connection lost: {error_msg}[/{ERROR_RED}]")
            self.console.print(f"[{WARN_AMBER}]The gateway may have restarted. Try /quit and restart.[/{WARN_AMBER}]")
            self.running = False

    async def _switch_chat(self, chat_id: str):
        """Disconnect from current chat and reconnect to a different one."""
        if self.ws_client:
            await self.ws_client.disconnect()

        self.chat_id = chat_id
        self.ws_client = ClothoWebSocketClient(
            self.host, self.port, self.chat_id, self.token
        )
        await self.ws_client.connect()
        self.ws_client.on_message(self.handle_message)
        asyncio.create_task(self.ws_client.listen())

        # Re-apply the active profile to the new session
        if self.active_profile:
            try:
                self.api_client.set_active_profile(self.chat_id, self.active_profile)
            except Exception as e:
                self.console.print(f"[{WARN_AMBER}]Warning: Could not apply profile '{self.active_profile}': {e}[/{WARN_AMBER}]")

        self.console.print(f"[{DIM}]Connected to chat: {self.chat_id}[/{DIM}]")

    async def repl_loop(self):
        """Main REPL loop."""
        # Show welcome banner — diagonal gradient from purple to green
        import pyfiglet
        banner = pyfiglet.figlet_format("CLOTHO", font="slant_relief")
        banner_lines = [ln.rstrip() for ln in banner.split("\n") if ln.strip()]
        max_width = max(len(ln) for ln in banner_lines) if banner_lines else 1
        num_lines = len(banner_lines)
        # Diagonal gradient: each character's color is based on (row + col)
        # normalized to [0, 1], interpolating RGB from purple to green
        pr, pg, pb = 0xd4, 0xa6, 0xe8  # PURPLE_BOLD
        gr, gg, gb = 0x7f, 0xdb, 0x8a  # GREEN
        self.console.print()
        for row, line in enumerate(banner_lines):
            text = Text()
            for col, ch in enumerate(line):
                if ch == " ":
                    text.append(ch)
                    continue
                # t=0 is top-left (purple), t=1 is bottom-right (green)
                t = (row / max(num_lines - 1, 1) + col / max(max_width - 1, 1)) / 2
                r = int(pr + (gr - pr) * t)
                g = int(pg + (gg - pg) * t)
                b = int(pb + (gb - pb) * t)
                text.append(ch, style=f"bold #{r:02x}{g:02x}{b:02x}")
            self.console.print(text, justify="center")
        self.console.print()
        tagline = Text("AI Coding Agent", style=f"italic {DIM}")
        self.console.print(tagline, justify="center")
        self.console.print()
        hints = Text()
        hints.append("  /help", style=GREEN)
        hints.append(" commands  ", style=DIM)
        hints.append("/quit", style=GREEN)
        hints.append(" exit", style=DIM)
        self.console.print(hints, justify="center")
        self.console.print()

        if self.initial_prompt:
            await self._send_and_wait(self.initial_prompt)

        while self.running:
            try:
                # Get input with escape-to-cancel hint
                user_input = await self._input.prompt()

                if not user_input.strip():
                    continue

                # Handle commands
                if user_input.startswith("/"):
                    await self.handle_command(user_input)
                else:
                    await self._send_and_wait(user_input)

            except CancelledInput:
                # User pressed Escape - cancel current request if one is running
                if self.spinner or self._live:
                    self._stop_spinner()
                    self._stop_live()
                    if self.ws_client:
                        await self.ws_client.cancel()
                    cancel_msg = Text()
                    cancel_msg.append("  ⊹ Cancelled", style=f"{WARN_AMBER}")
                    self.console.print(cancel_msg)
                # Otherwise just ignore the escape
            except KeyboardInterrupt:
                self.console.print(f"\n[{WARN_AMBER}]Use /quit to exit[/{WARN_AMBER}]")
            except EOFError:
                break
            except Exception as e:
                self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")

    async def _send_and_wait(self, message: str):
        """Send a message to the agent and wait for the complete response.

        Args:
            message: Message text to send
        """
        self.response_complete.clear()
        await self.ws_client.send_message(message, stream=self.streaming)

        # Start particle spinner
        self.spinner = ParticleSpinner(self.console, self.loading_phrases[0])
        self.spinner.start()

        # Start phrase rotation in background
        self.rotating_phrases = True
        rotation_task = asyncio.create_task(self.rotate_loading_phrases())

        try:
            # Wait for response or tool approval request
            while True:
                await self.response_complete.wait()

                if self.pending_approval:
                    response = await self._input.confirm("Approve tools? (y/n):")
                    if response.lower() == "y":
                        await self.ws_client.approve_tools()
                        approved = Text()
                        approved.append("  ✦ Approved", style=f"bold {GREEN}")
                        self.console.print(approved)
                    else:
                        await self.ws_client.deny_tools()
                        denied = Text()
                        denied.append("  ✦ Denied", style=f"bold {ERROR_RED}")
                        self.console.print(denied)
                    self.pending_approval = False

                    # Restart particle spinner for tool execution
                    self.spinner = ParticleSpinner(self.console, self.loading_phrases[0])
                    self.spinner.start()
                    self.rotating_phrases = True
                    rotation_task = asyncio.create_task(self.rotate_loading_phrases())

                    self.response_complete.clear()
                    continue
                else:
                    break
        finally:
            self.rotating_phrases = False
            self._stop_spinner()
            try:
                rotation_task.cancel()
            except Exception:
                pass

    async def handle_command(self, command: str):
        """Process slash command.

        Args:
            command: Command string starting with /
        """
        parts = command.split()
        cmd = parts[0][1:]  # Remove leading /
        args = parts[1:]

        if cmd == "quit":
            self.running = False
        elif cmd == "help":
            self.show_help()
        elif cmd == "profiles":
            self.command_handler.list_profiles()
        elif cmd == "profile":
            await self.command_handler.handle_profile(args, self.chat_id)
            # Track profile changes for chat switching
            if len(args) >= 2 and args[0] == "use":
                try:
                    current = self.api_client.get_active_profile(self.chat_id)
                    if current:
                        self.active_profile = current
                except Exception:
                    pass
        elif cmd == "permissions":
            self.command_handler.show_permissions()
        elif cmd == "permission":
            await self.command_handler.handle_permission(args)
        elif cmd == "chats":
            self.command_handler.list_chats()
        elif cmd == "chat":
            new_chat_id = self.command_handler.handle_chat(args)
            if new_chat_id and new_chat_id != self.chat_id:
                await self._switch_chat(new_chat_id)
        elif cmd == "stream":
            self.handle_stream(args)
        elif cmd == "sandbox":
            self.command_handler.handle_sandbox(args)
        else:
            self.console.print(f"[{ERROR_RED}]Unknown command: /{cmd}[/{ERROR_RED}]")
            self.console.print(f"Type [{GREEN}]/help[/{GREEN}] for available commands")

    def handle_stream(self, args: list[str]):
        """Toggle or show streaming mode."""
        if not args:
            state = f"[{GREEN}]on[/{GREEN}]" if self.streaming else f"[{WARN_AMBER}]off[/{WARN_AMBER}]"
            self.console.print(f"Streaming: {state}")
            return

        if args[0] == "on":
            self.streaming = True
            self.console.print(f"[{GREEN}]Streaming enabled[/{GREEN}]")
        elif args[0] == "off":
            self.streaming = False
            self.console.print(f"[{WARN_AMBER}]Streaming disabled[/{WARN_AMBER}]")
        else:
            self.console.print(f"[{ERROR_RED}]Usage: /stream [on|off][/{ERROR_RED}]")

    def show_help(self):
        """Display help text."""
        help_text = Text()
        help_text.append("Clotho Commands:\n\n", style=f"bold {GREEN_BOLD}")

        commands = [
            ("/help", "Show this help"),
            ("/quit", "Exit Clotho"),
            ("/profiles", "List model profiles"),
            ("/profile add", "Add new profile"),
            ("/profile use <name>", "Switch to profile for this chat"),
            ("/profile default <name>", "Set default profile"),
            ("/permissions", "Show permission config"),
            ("/permission set <tool> <level>", "Set tool override (allow/ask/deny)"),
            ("/permission clear <tool>", "Clear tool override"),
            ("/permission mode <mode>", "Set mode (interactive/autonomous/readonly)"),
            ("/chats", "List all chats"),
            ("/chat new", "Create and switch to a new chat"),
            ("/chat <id>", "Switch to an existing chat"),
            ("/stream", "Show streaming status"),
            ("/stream on|off", "Toggle response streaming"),
            ("/sandbox", "Show sandbox status"),
            ("/sandbox on|off", "Enable or disable the sandbox"),
            ("/sandbox build", "Build the sandbox Docker image"),
        ]

        max_cmd_len = max(len(cmd) for cmd, _ in commands)
        for cmd, desc in commands:
            help_text.append(f"  {cmd}", style=GREEN)
            padding = " " * (max_cmd_len - len(cmd) + 4)
            help_text.append(f"{padding}{desc}\n", style=DIM)

        help_text.append("\nType a message to chat with the agent.", style="")
        self.console.print(Panel(
            help_text,
            title=f"[bold {GREEN}]Help[/bold {GREEN}]",
            border_style=PURPLE,
        ))


def run_noninteractive(
    host: str = "127.0.0.1",
    port: int = 8000,
    prompt: str = "",
    chat_id: str | None = None,
    timeout: int = 300,
):
    """Run in non-interactive mode: send prompt, collect response, print to stdout, exit.

    Output is the raw agent text with no Rich formatting, suitable for piping.
    Tool requests are auto-approved (DENY overrides are still respected by the
    gateway before the request reaches the client). Errors go to stderr.

    Args:
        host: Gateway host address
        port: Gateway port number
        prompt: Prompt to send to the agent
        chat_id: Optional existing chat ID to resume
        timeout: Seconds to wait before raising a timeout error
    """
    from exceptions import SystemException
    from gateway.auth.token import load_token

    token = load_token()
    if not token:
        raise SystemException(message="No auth token found. Run: clotho setup", exit_code=1)

    async def async_main():
        api = ClothoAPIClient(host, port, token)

        if chat_id:
            chats = api.list_chats()
            ids = [c["chat_id"] for c in chats]
            if chat_id not in ids:
                raise SystemException(message=f"Chat not found: {chat_id}", exit_code=2)
            resolved = chat_id
        else:
            resolved = api.create_chat()

        ws = ClothoWebSocketClient(host, port, resolved, token)
        await ws.connect()

        done = asyncio.Event()
        error_holder: list[str] = []
        buffer: list[str] = []

        def on_message(msg: dict):
            msg_type = msg.get("type")
            data = msg.get("data", {})

            if msg_type in ("agent.text", "agent.text_delta"):
                buffer.append(data.get("text", ""))
            elif msg_type == "agent.tool_request":
                asyncio.create_task(ws.approve_tools())
            elif msg_type == "agent.error":
                error_holder.append(data.get("message", "Unknown error"))
                done.set()
            elif msg_type == "agent.turn_complete":
                done.set()
            elif msg_type == "connection.error":
                error_holder.append(data.get("message", "Connection lost"))
                done.set()

        ws.on_message(on_message)
        listen_task = asyncio.create_task(ws.listen())
        try:
            await ws.send_message(prompt, stream=True)
            try:
                await asyncio.wait_for(done.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                raise SystemException(
                    message=f"Agent run timed out after {timeout} seconds",
                    exit_code=1,
                )
        finally:
            listen_task.cancel()
            try:
                await listen_task
            except (asyncio.CancelledError, Exception):
                pass
            await ws.disconnect()

        if error_holder:
            raise SystemException(message=error_holder[0], exit_code=1)

        result = "".join(buffer)
        sys.stdout.write(result)
        if result and not result.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()

    try:
        with GatewayManager(host, port):
            asyncio.run(async_main())
    except SystemException:
        raise
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        raise SystemException(message=str(exc), exit_code=1) from exc


def run_repl(host: str = "127.0.0.1", port: int = 8000, initial_prompt: str | None = None, chat_id: str | None = None):
    """Run interactive REPL with gateway.

    Args:
        host: Gateway host address
        port: Gateway port number
        initial_prompt: Optional prompt to send automatically on startup
        chat_id: Optional existing chat ID to resume
    """
    repl = ClothoREPL(host, port, initial_prompt=initial_prompt, chat_id=chat_id)

    async def async_main():
        with GatewayManager(host, port):
            repl.console.print(f"[{DIM}]Starting gateway...[/{DIM}]")
            repl.setup()
            await repl.start_session()
            repl.console.print(f"[{DIM}]Connected to chat: {repl.chat_id}[/{DIM}]")
            await repl.repl_loop()

            # Cleanup
            if repl.ws_client:
                await repl.ws_client.disconnect()

    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        repl.console.print(f"\n[{WARN_AMBER}]Goodbye![/{WARN_AMBER}]")
