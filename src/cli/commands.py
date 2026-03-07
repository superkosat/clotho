"""Command handlers for REPL slash commands."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cli.api_client import ClothoAPIClient


class CommandHandler:
    """Handles slash commands in REPL."""

    def __init__(self, console: Console, api_client: ClothoAPIClient):
        """Initialize command handler.

        Args:
            console: Rich console for output
            api_client: API client for REST operations
        """
        self.console = console
        self.api = api_client

    def list_profiles(self):
        """Display profiles as table."""
        try:
            data = self.api.list_profiles()
            default = data.get("default")
            profiles = data.get("profiles", {})

            if not profiles:
                self.console.print("[yellow]No profiles found[/yellow]")
                return

            table = Table(title="Model Profiles")
            table.add_column("Name", style="cyan")
            table.add_column("Provider")
            table.add_column("Model")
            table.add_column("Default", style="green")

            for name, profile in profiles.items():
                is_default = "✓" if name == default else ""
                table.add_row(
                    name,
                    profile.get("provider", ""),
                    profile.get("model", ""),
                    is_default
                )

            self.console.print(table)
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")

    async def handle_profile(self, args: list[str], chat_id: str | None = None):
        """Handle profile subcommands.

        Args:
            args: Command arguments
            chat_id: Current chat ID (for 'use' command)
        """
        if not args:
            self.list_profiles()
            return

        subcommand = args[0]

        if subcommand == "add":
            await self.add_profile()
        elif subcommand == "use" and len(args) > 1:
            profile_name = args[1]
            if not chat_id:
                self.console.print("[red]No active chat session[/red]")
                return
            try:
                self.api.set_active_profile(chat_id, profile_name)
                self.console.print(f"[green]✓ Switched to profile: {profile_name}[/green]")
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
        elif subcommand == "default" and len(args) > 1:
            profile_name = args[1]
            try:
                self.api.set_default_profile(profile_name)
                self.console.print(f"[green]✓ Set default profile: {profile_name}[/green]")
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
        else:
            self.console.print("[red]Invalid profile command[/red]")
            self.console.print("Usage: /profile [add|use <name>|default <name>]")

    async def add_profile(self):
        """Interactive profile creation."""
        import asyncio
        try:
            name = await asyncio.to_thread(self.console.input, "Profile name: ")
            provider = await asyncio.to_thread(self.console.input, "Provider (openai/ollama/anthropic): ")
            model = await asyncio.to_thread(self.console.input, "Model: ")
            base_url = await asyncio.to_thread(self.console.input, "Base URL (optional): ")
            api_key = await asyncio.to_thread(self.console.input, "API Key (optional): ")

            profile = {
                "provider": provider,
                "model": model,
            }
            if base_url:
                profile["base_url"] = base_url
            if api_key:
                profile["api_key"] = api_key

            self.api.create_profile(name, profile)
            self.console.print(f"[green]✓ Created profile: {name}[/green]")
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")

    def show_permissions(self):
        """Display current permissions."""
        try:
            perms = self.api.get_permissions()

            mode = perms.get("mode", "unknown")
            overrides = perms.get("tool_overrides", {})

            panel_content = f"[bold]Mode:[/bold] {mode}\n\n"

            if overrides:
                panel_content += "[bold]Tool Overrides:[/bold]\n"
                for tool, level in overrides.items():
                    panel_content += f"  {tool}: {level}\n"
            else:
                panel_content += "[dim]No tool overrides[/dim]"

            self.console.print(Panel(panel_content, title="Permissions"))
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")

    async def handle_permission(self, args: list[str]):
        """Handle permission subcommands.

        Args:
            args: Command arguments
        """
        if not args:
            self.show_permissions()
            return

        subcommand = args[0]

        if subcommand == "set" and len(args) >= 3:
            tool_name = args[1]
            level = args[2]
            await self.set_tool_permission(tool_name, level)
        elif subcommand == "clear" and len(args) >= 2:
            tool_name = args[1]
            await self.clear_tool_permission(tool_name)
        elif subcommand == "mode" and len(args) >= 2:
            mode = args[1]
            await self.set_permission_mode(mode)
        else:
            self.console.print("[red]Invalid permission command[/red]")
            self.console.print("Usage:")
            self.console.print("  /permission                 Show current permissions")
            self.console.print("  /permission set <tool> <level>   Set tool override (allow/ask/deny)")
            self.console.print("  /permission clear <tool>    Clear tool override")
            self.console.print("  /permission mode <mode>     Set mode (interactive/autonomous/readonly)")

    async def set_tool_permission(self, tool_name: str, level: str):
        """Set permission override for a specific tool.

        Args:
            tool_name: Name of the tool
            level: Permission level (allow/ask/deny)
        """
        valid_levels = ["allow", "ask", "deny"]
        if level not in valid_levels:
            self.console.print(f"[red]Invalid level: {level}[/red]")
            self.console.print(f"Must be one of: {', '.join(valid_levels)}")
            return

        try:
            # Get current permissions
            perms = self.api.get_permissions()
            overrides = perms.get("tool_overrides", {})

            # Update the specific tool
            overrides[tool_name] = level

            # Save back
            self.api.update_permissions(perms.get("mode"), overrides)
            self.console.print(f"[green]✓ Set {tool_name} → {level}[/green]")
        except Exception as e:
            error_msg = str(e)
            self.console.print(f"[red]Error: {error_msg}[/red]")

            # If it's an invalid tool name error, show available tools
            if "Invalid tool name" in error_msg or "400" in error_msg:
                try:
                    tools = self.api.get_available_tools()
                    self.console.print(f"[yellow]Available tools: {', '.join(tools)}[/yellow]")
                except Exception:
                    pass  # Ignore errors fetching tool list

    async def clear_tool_permission(self, tool_name: str):
        """Clear permission override for a specific tool.

        Args:
            tool_name: Name of the tool
        """
        try:
            # Get current permissions
            perms = self.api.get_permissions()
            overrides = perms.get("tool_overrides", {})

            # Check if override exists
            if tool_name not in overrides:
                self.console.print(f"[yellow]No override set for: {tool_name}[/yellow]")
                return

            # Remove the override
            del overrides[tool_name]

            # Save back
            self.api.update_permissions(perms.get("mode"), overrides)
            self.console.print(f"[green]✓ Cleared override for {tool_name}[/green]")
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")

    async def set_permission_mode(self, mode: str):
        """Set global permission mode.

        Args:
            mode: Permission mode (interactive/autonomous/readonly)
        """
        valid_modes = ["interactive", "autonomous", "readonly"]
        if mode not in valid_modes:
            self.console.print(f"[red]Invalid mode: {mode}[/red]")
            self.console.print(f"Must be one of: {', '.join(valid_modes)}")
            return

        try:
            # Get current permissions to preserve overrides
            perms = self.api.get_permissions()
            overrides = perms.get("tool_overrides", {})

            # Update mode
            self.api.update_permissions(mode, overrides)
            self.console.print(f"[green]✓ Set mode to: {mode}[/green]")
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")

    def list_chats(self):
        """Display chat list as table."""
        try:
            chats = self.api.list_chats()

            if not chats:
                self.console.print("[yellow]No chats found[/yellow]")
                return

            table = Table(title="Chat Sessions")
            table.add_column("Chat ID", style="cyan")

            for chat in chats:
                table.add_row(chat["chat_id"])

            self.console.print(table)
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")

    def handle_chat(self, args: list[str]) -> str | None:
        """Handle chat subcommands. Returns new chat_id if switched, else None.

        Args:
            args: Command arguments
        """
        if not args:
            self.list_chats()
            return None

        subcommand = args[0]

        if subcommand == "new":
            try:
                chat_id = self.api.create_chat()
                self.console.print(f"[green]Created new chat: {chat_id}[/green]")
                return chat_id
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
                return None
        else:
            # Treat the argument as a chat ID to switch to
            chat_id = subcommand
            try:
                chats = self.api.list_chats()
                chat_ids = [c["chat_id"] for c in chats]
                if chat_id not in chat_ids:
                    self.console.print(f"[red]Chat not found: {chat_id}[/red]")
                    return None
                self.console.print(f"[green]Switched to chat: {chat_id}[/green]")
                return chat_id
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
                return None

    def handle_sandbox(self, args: list[str]) -> None:
        """Handle sandbox subcommands.

        Args:
            args: Command arguments
        """
        if not args:
            try:
                enabled = self.api.get_sandbox()
                state = "[green]enabled[/green]" if enabled else "[yellow]disabled[/yellow]"
                self.console.print(f"Sandbox: {state}")
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
            return

        subcommand = args[0]
        if subcommand == "on":
            try:
                self.api.set_sandbox(True)
                self.console.print("[green]Sandbox enabled[/green]")
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
        elif subcommand == "off":
            try:
                self.api.set_sandbox(False)
                self.console.print("[yellow]Sandbox disabled[/yellow]")
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
        elif subcommand == "build":
            try:
                self.console.print("[dim]Building sandbox image (this may take a few minutes)...[/dim]")
                self.api.build_sandbox()
                self.console.print("[green]Sandbox image built successfully[/green]")
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")
        else:
            self.console.print("[red]Invalid sandbox command[/red]")
            self.console.print("Usage: /sandbox [on|off|build]")
