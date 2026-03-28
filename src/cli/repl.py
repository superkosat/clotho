"""Rich-based REPL for Clotho agent interaction."""

import asyncio
import sys

from rich.console import Console
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
from cli.picker import pick, PickerCancelled
from cli.ui import LOADING_PHRASES, print_error, print_muted, print_warning, styled_panel
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
        self._input = ClothoInput()

    def setup(self):
        """Load token and create clients."""
        from gateway.auth.token import load_token

        self.token = load_token()
        if not self.token:
            print_error(self.console, "No auth token found. Run: clotho setup")
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
                phrase = LOADING_PHRASES[phrase_index]
                self.spinner.update_label(phrase)
                phrase_index = (phrase_index + 1) % len(LOADING_PHRASES)
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
        """Flush and reset the streaming response buffer."""
        if self._response_buffer:
            if not self._response_buffer.endswith("\n"):
                self.console.file.write("\n")
                self.console.file.flush()
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

            # Write text directly to the terminal — no Live/Markdown re-rendering.
            # This avoids two Rich Live issues: (1) red ellipsis truncation when
            # content exceeds terminal height, (2) visual jumping from cursor-up
            # redraws on growing content.
            self.console.file.write(text)
            self.console.file.flush()

        elif msg_type == "agent.tool_request":
            self._stop_spinner()
            self._stop_live()

            tool_calls = data.get("tool_calls", [])
            self.console.print()
            for tool in tool_calls:
                tool_name = tool.get("name", "unknown")
                tool_args = tool.get("arguments", {})
                line = Text()
                line.append("● ", style=PURPLE)
                line.append(tool_name, style=f"bold {PURPLE_BOLD}")
                line.append(f"  {tool_args}", style=DIM)
                self.console.print(line)

            # Set pending approval flag and wake up the loop
            self.pending_approval = True
            self.response_complete.set()

        elif msg_type == "agent.tool_result":
            # Tool executed
            content = data.get("content", "")
            is_error = data.get("is_error", False)

            if is_error:
                print_error(self.console, f"Tool error: {content}")
            else:
                # Truncate long results
                if len(content) > 500:
                    content = content[:500] + "... (truncated)"
                print_muted(self.console, f"Result: {content}")

        elif msg_type == "agent.compaction_started":
            tokens_before = data.get("tokens_before", 0)
            context_window = data.get("context_window", 0)
            pct = int(tokens_before / context_window * 100) if context_window else 0
            self._stop_spinner()
            self._stop_live()
            self.spinner = ParticleSpinner(self.console, f"Compacting context ({pct}% full)")
            self.spinner.start()

        elif msg_type == "agent.context_compacted":
            self._stop_spinner()
            tokens_before = data.get("tokens_before", 0)
            tokens_after = data.get("tokens_after")
            turns_removed = data.get("turns_removed", 0)
            compact_msg = Text()
            compact_msg.append("  ⊹ Context compacted", style=f"bold {PURPLE_BOLD}")
            if tokens_after is not None:
                compact_msg.append(
                    f"  {tokens_before:,} → {tokens_after:,} tokens, {turns_removed} turns summarized",
                    style=DIM
                )
            else:
                compact_msg.append(f"  {turns_removed} turns summarized", style=DIM)
            self.console.print(compact_msg)

            # Restart spinner — the agent continues processing after compaction
            self.spinner = ParticleSpinner(self.console, LOADING_PHRASES[0])
            self.spinner.start()

        elif msg_type == "agent.error":
            self._stop_spinner()
            self._stop_live()
            error = data.get("message", "Unknown error")
            print_error(self.console, f"\nError: {error}")
            self.response_complete.set()

        elif msg_type == "agent.turn_complete":
            self._stop_spinner()

            # Ensure streamed response ends with a newline
            if self._response_buffer and not self._response_buffer.endswith("\n"):
                self.console.file.write("\n")
                self.console.file.flush()
            self._response_buffer = ""

            stop_reason = data.get("stop_reason", "")
            model = data.get("model", "")
            done = Text()
            done.append("● Done", style=f"bold {GREEN}")
            done.append(f" ({model} - {stop_reason})", style=DIM)
            self.console.print(done)
            self.pending_approval = False
            self.response_complete.set()

        elif msg_type == "connection.error":
            self._stop_spinner()
            self._stop_live()
            error_msg = data.get("message", "Unknown connection error")
            print_error(self.console, f"\n⊹ WebSocket connection lost: {error_msg}")
            print_warning(self.console, "The gateway may have restarted. Try /exit and restart.")
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
                print_warning(self.console, f"Warning: Could not apply profile '{self.active_profile}': {e}")

        print_muted(self.console, f"Connected to chat: {self.chat_id}")

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
        hints.append("/exit", style=GREEN)
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
                if self.spinner or self._response_buffer:
                    self._stop_spinner()
                    self._stop_live()
                    if self.ws_client:
                        await self.ws_client.cancel()
                    cancel_msg = Text()
                    cancel_msg.append("  ⊹ Cancelled", style=f"{WARN_AMBER}")
                    self.console.print(cancel_msg)
                # Otherwise just ignore the escape
            except KeyboardInterrupt:
                print_warning(self.console, "\nUse /exit to quit")
            except EOFError:
                break
            except Exception as e:
                print_error(self.console, f"Error: {e}")

    async def _send_and_wait(self, message: str):
        """Send a message to the agent and wait for the complete response.

        Args:
            message: Message text to send
        """
        self.response_complete.clear()
        await self.ws_client.send_message(message, stream=self.streaming)

        # Start particle spinner
        self.spinner = ParticleSpinner(self.console, LOADING_PHRASES[0])
        self.spinner.start()

        # Start phrase rotation in background
        self.rotating_phrases = True
        rotation_task = asyncio.create_task(self.rotate_loading_phrases())

        try:
            # Wait for response or tool approval request
            while True:
                await self.response_complete.wait()

                if self.pending_approval:
                    try:
                        choice = await pick(
                            "Tool approval",
                            [("allow", "✓ Allow"), ("deny", "✗ Deny")],
                        )
                    except PickerCancelled:
                        choice = "deny"

                    if choice == "allow":
                        await self.ws_client.approve_tools()
                    else:
                        await self.ws_client.deny_tools()
                    self.pending_approval = False

                    # Restart particle spinner for tool execution
                    self.spinner = ParticleSpinner(self.console, LOADING_PHRASES[0])
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

        if cmd in ("quit", "exit"):
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
        elif cmd == "compact":
            await self.command_handler.handle_compact(self.chat_id)
        elif cmd == "context":
            self.command_handler.handle_context(self.chat_id)
        else:
            print_error(self.console, f"Unknown command: /{cmd}")
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
            print_warning(self.console, "Streaming disabled")
        else:
            print_error(self.console, "Usage: /stream [on|off]")

    def show_help(self):
        """Display help text."""
        help_text = Text()
        help_text.append("Clotho Commands:\n\n", style=f"bold {GREEN_BOLD}")

        commands = [
            ("/help", "Show this help"),
            ("/exit", "Exit Clotho"),
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
            ("/compact", "Summarize old conversation turns to free context space"),
            ("/context", "Show context window usage"),
        ]

        max_cmd_len = max(len(cmd) for cmd, _ in commands)
        for cmd, desc in commands:
            help_text.append(f"  {cmd}", style=GREEN)
            padding = " " * (max_cmd_len - len(cmd) + 4)
            help_text.append(f"{padding}{desc}\n", style=DIM)

        help_text.append("\nType a message to chat with the agent.", style="")
        styled_panel(self.console, help_text, "Help")


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
            print_muted(repl.console, "Starting gateway...")
            repl.setup()
            await repl.start_session()
            print_muted(repl.console, f"Connected to chat: {repl.chat_id}")
            await repl.repl_loop()

            # Cleanup
            if repl.ws_client:
                await repl.ws_client.disconnect()

    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print_warning(repl.console, "\nGoodbye!")
