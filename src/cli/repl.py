"""Rich-based REPL for Clotho agent interaction."""

import asyncio
import sys

from rich.console import Console
from rich.panel import Panel

from cli.api_client import ClothoAPIClient
from cli.commands import CommandHandler
from cli.gateway_manager import GatewayManager
from cli.ws_client import ClothoWebSocketClient


class ClothoREPL:
    """Rich-based REPL for Clotho agent interaction."""

    def __init__(self, host: str, port: int):
        """Initialize REPL.

        Args:
            host: Gateway host address
            port: Gateway port number
        """
        self.console = Console()
        self.host = host
        self.port = port
        self.token = None
        self.chat_id = None
        self.api_client = None
        self.ws_client = None
        self.command_handler = None
        self.running = True
        self.pending_approval = False
        self.current_status = None
        self.rotating_phrases = False
        self.response_complete = asyncio.Event()
        self.active_profile = None
        self.loading_phrases = [
            "Thinking...",
            "Processing...",
            "Analyzing...",
            "Working on it...",
            "Computing...",
            "Considering...",
            "Pondering...",
            "Cogitating...",
            "Deliberating...",
            "Reasoning...",
        ]

    def setup(self):
        """Load token and create clients."""
        from gateway.auth.token import load_token

        self.token = load_token()
        if not self.token:
            self.console.print("[red]No auth token found. Run: clotho setup[/red]")
            sys.exit(1)

        # Create API client
        self.api_client = ClothoAPIClient(self.host, self.port, self.token)

        # Create command handler
        self.command_handler = CommandHandler(self.console, self.api_client)

    async def start_session(self):
        """Create or resume chat session."""
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
        while self.rotating_phrases and self.current_status:
            try:
                phrase = self.loading_phrases[phrase_index]
                self.current_status.update(f"[bold cyan]{phrase}[/bold cyan]")
                phrase_index = (phrase_index + 1) % len(self.loading_phrases)
                await asyncio.sleep(1.5)  # Rotate every 1.5 seconds
            except Exception:
                break

    def handle_message(self, message: dict):
        """Handle incoming WebSocket message.

        Args:
            message: Message from server
        """
        msg_type = message.get("type")
        data = message.get("data", {})

        if msg_type == "agent.text":
            # Stop loading status when first text arrives
            if self.current_status:
                self.rotating_phrases = False
                self.current_status.stop()
                self.current_status = None

            # Stream text chunk
            text = data.get("text", "")
            self.console.print(text, end="")

        elif msg_type == "agent.tool_request":
            # Stop loading status if active
            if self.current_status:
                self.rotating_phrases = False
                self.current_status.stop()
                self.current_status = None

            # Tool approval required - display all tools
            tool_calls = data.get("tool_calls", [])
            self.console.print(f"\n[yellow]🔧 Tool approval required ({len(tool_calls)} tool(s)):[/yellow]")
            for tool in tool_calls:
                tool_name = tool.get("name", "unknown")
                tool_args = tool.get("arguments", {})
                self.console.print(f"  • {tool_name}: {tool_args}")

            # Set pending approval flag and wake up the loop
            self.pending_approval = True
            self.response_complete.set()

        elif msg_type == "agent.tool_result":
            # Tool executed
            content = data.get("content", "")
            is_error = data.get("is_error", False)

            if is_error:
                self.console.print(f"[red]Tool error: {content}[/red]")
            else:
                # Truncate long results
                if len(content) > 500:
                    content = content[:500] + "... (truncated)"
                self.console.print(f"[dim]Result: {content}[/dim]")

        elif msg_type == "agent.error":
            # Stop loading status if active
            if self.current_status:
                self.rotating_phrases = False
                self.current_status.stop()
                self.current_status = None
            # Print error
            error = data.get("message", "Unknown error")
            self.console.print(f"\n[red]Error: {error}[/red]")
            # Signal completion
            self.response_complete.set()

        elif msg_type == "agent.turn_complete":
            # Stop loading status if active
            if self.current_status:
                self.rotating_phrases = False
                self.current_status.stop()
                self.current_status = None

            # Agent finished - add newline after response text
            self.console.print()  # Newline after agent's last output
            stop_reason = data.get("stop_reason", "")
            model = data.get("model", "")
            self.console.print(f"[green]✓ Done[/green] [dim]({model} - {stop_reason})[/dim]")
            self.pending_approval = False
            # Signal that response is complete
            self.response_complete.set()

        elif msg_type == "connection.error":
            # WebSocket connection error
            if self.current_status:
                self.rotating_phrases = False
                self.current_status.stop()
                self.current_status = None
            error_msg = data.get("message", "Unknown connection error")
            self.console.print(f"\n[red]⚠ WebSocket connection lost: {error_msg}[/red]")
            self.console.print("[yellow]The gateway may have restarted. Try /quit and restart.[/yellow]")
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
                self.console.print(f"[yellow]Warning: Could not apply profile '{self.active_profile}': {e}[/yellow]")

        self.console.print(f"[dim]Connected to chat: {self.chat_id}[/dim]")

    async def repl_loop(self):
        """Main REPL loop."""
        # Show welcome message
        self.console.print(Panel(
            "[bold cyan]Clotho AI Coding Agent[/bold cyan]\n\n"
            "Type a message to chat with the agent.\n"
            "Type [cyan]/help[/cyan] for commands.\n"
            "Type [cyan]/quit[/cyan] to exit.",
            title="Welcome"
        ))

        while self.running:
            try:
                # Display prompt
                user_input = await asyncio.to_thread(
                    self.console.input,
                    "[bold cyan]>[/bold cyan] "
                )

                if not user_input.strip():
                    continue

                # Handle commands
                if user_input.startswith("/"):
                    await self.handle_command(user_input)
                else:
                    # Send to agent and show loading spinner
                    self.response_complete.clear()
                    await self.ws_client.send_message(user_input)

                    # Show loading status with first phrase
                    self.current_status = self.console.status(
                        f"[bold cyan]{self.loading_phrases[0]}[/bold cyan]",
                        spinner="dots"
                    )
                    self.current_status.start()

                    # Start phrase rotation in background
                    self.rotating_phrases = True
                    rotation_task = asyncio.create_task(self.rotate_loading_phrases())

                    # Wait for response or tool approval request
                    while True:
                        await self.response_complete.wait()

                        # Check if tool approval is needed
                        if self.pending_approval:
                            # Prompt for approval
                            response = await asyncio.to_thread(
                                self.console.input,
                                "[green]Approve tools? (y/n):[/green] "
                            )
                            if response.lower() == "y":
                                await self.ws_client.approve_tools()
                                self.console.print("[green]✓ Approved[/green]")
                            else:
                                await self.ws_client.deny_tools()
                                self.console.print("[red]✗ Denied[/red]")
                            self.pending_approval = False

                            # Restart loading spinner for tool execution and response
                            self.current_status = self.console.status(
                                f"[bold cyan]{self.loading_phrases[0]}[/bold cyan]",
                                spinner="dots"
                            )
                            self.current_status.start()
                            self.rotating_phrases = True
                            rotation_task = asyncio.create_task(self.rotate_loading_phrases())

                            # Clear and wait for actual response
                            self.response_complete.clear()
                            continue
                        else:
                            # Response is complete
                            break

                    # Stop rotation and spinner
                    self.rotating_phrases = False
                    if self.current_status:
                        self.current_status.stop()
                        self.current_status = None
                    try:
                        rotation_task.cancel()
                    except Exception:
                        pass

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Use /quit to exit[/yellow]")
            except EOFError:
                break
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")

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
        elif cmd == "sandbox":
            self.command_handler.handle_sandbox(args)
        else:
            self.console.print(f"[red]Unknown command: /{cmd}[/red]")
            self.console.print("Type [cyan]/help[/cyan] for available commands")

    def show_help(self):
        """Display help text."""
        help_text = """[bold]Clotho Commands:[/bold]

[cyan]/help[/cyan]                              Show this help
[cyan]/quit[/cyan]                              Exit Clotho
[cyan]/profiles[/cyan]                          List model profiles
[cyan]/profile add[/cyan]                       Add new profile
[cyan]/profile use <name>[/cyan]               Switch to profile for this chat
[cyan]/profile default <name>[/cyan]           Set default profile
[cyan]/permissions[/cyan]                       Show permission config
[cyan]/permission set <tool> <level>[/cyan]    Set tool override (allow/ask/deny)
[cyan]/permission clear <tool>[/cyan]          Clear tool override
[cyan]/permission mode <mode>[/cyan]           Set mode (interactive/autonomous/readonly)
[cyan]/chats[/cyan]                             List all chats
[cyan]/chat new[/cyan]                          Create and switch to a new chat
[cyan]/chat <id>[/cyan]                         Switch to an existing chat
[cyan]/sandbox[/cyan]                           Show sandbox status
[cyan]/sandbox on|off[/cyan]                    Enable or disable the sandbox
[cyan]/sandbox build[/cyan]                     Build the sandbox Docker image

Type a message to chat with the agent.
"""
        self.console.print(Panel(help_text, title="Help"))


def run_repl(host: str = "127.0.0.1", port: int = 8000):
    """Run interactive REPL with gateway.

    Args:
        host: Gateway host address
        port: Gateway port number
    """
    repl = ClothoREPL(host, port)

    async def async_main():
        with GatewayManager(host, port):
            repl.console.print("[dim]Starting gateway...[/dim]")
            repl.setup()
            await repl.start_session()
            repl.console.print(f"[dim]Connected to chat: {repl.chat_id}[/dim]")
            await repl.repl_loop()

            # Cleanup
            if repl.ws_client:
                await repl.ws_client.disconnect()

    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        repl.console.print("\n[yellow]Goodbye![/yellow]")
