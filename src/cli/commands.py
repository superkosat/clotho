"""Command handlers for REPL slash commands."""

import asyncio

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.api_client import ClothoAPIClient
from cli.theme import GREEN, GREEN_BOLD, PURPLE, PURPLE_BOLD, DIM, ERROR_RED, WARN_AMBER


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
                self.console.print(f"[{WARN_AMBER}]No profiles found[/{WARN_AMBER}]")
                return

            table = Table(title="Model Profiles", border_style=PURPLE)
            table.add_column("Name", style=GREEN)
            table.add_column("Provider")
            table.add_column("Model")
            table.add_column("Default", style=GREEN)

            for name, profile in profiles.items():
                is_default = "✦" if name == default else ""
                table.add_row(
                    name,
                    profile.get("provider", ""),
                    profile.get("model", ""),
                    is_default
                )

            self.console.print(table)
        except Exception as e:
            self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")

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
                self.console.print(f"[{ERROR_RED}]No active chat session[/{ERROR_RED}]")
                return
            try:
                self.api.set_active_profile(chat_id, profile_name)
                self.console.print(f"[{GREEN}]✦ Switched to profile: {profile_name}[/{GREEN}]")
            except Exception as e:
                self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")
        elif subcommand == "default" and len(args) > 1:
            profile_name = args[1]
            try:
                self.api.set_default_profile(profile_name)
                self.console.print(f"[{GREEN}]✦ Set default profile: {profile_name}[/{GREEN}]")
            except Exception as e:
                self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")
        else:
            self.console.print(f"[{ERROR_RED}]Invalid profile command[/{ERROR_RED}]")
            self.console.print(f"Usage: /profile [add|use <name>|default <name>]")

    async def add_profile(self):
        """Interactive profile creation."""
        from agent.models.model_registry import lookup_model
        try:
            name = await asyncio.to_thread(self.console.input, "Profile name: ")
            provider = await asyncio.to_thread(self.console.input, "Provider (openai/ollama/anthropic): ")
            model = await asyncio.to_thread(self.console.input, "Model: ")
            base_url = await asyncio.to_thread(self.console.input, "Base URL (optional): ")
            api_key = await asyncio.to_thread(self.console.input, "API Key (optional): ")

            profile: dict = {"provider": provider, "model": model}
            if base_url:
                profile["base_url"] = base_url
            if api_key:
                profile["api_key"] = api_key

            # Resolve context limits from registry
            registry_entry = lookup_model(model)
            if registry_entry:
                profile["context_window"] = registry_entry["context_window"]
                profile["max_output_tokens"] = registry_entry["max_output_tokens"]
            else:
                self.console.print(
                    f"[{WARN_AMBER}]Model '{model}' is not in the known model registry.[/{WARN_AMBER}]"
                )
                self.console.print(
                    f"[{WARN_AMBER}]You must specify the context window. "
                    f"An inaccurate value may break the agent unexpectedly.[/{WARN_AMBER}]"
                )
                while True:
                    raw = await asyncio.to_thread(
                        self.console.input, "Context window (tokens, required): "
                    )
                    try:
                        profile["context_window"] = int(raw.strip().replace(",", ""))
                        break
                    except ValueError:
                        self.console.print(f"[{ERROR_RED}]Enter a whole number (e.g. 8192)[/{ERROR_RED}]")

                while True:
                    raw = await asyncio.to_thread(
                        self.console.input, "Max output tokens (tokens, required): "
                    )
                    try:
                        profile["max_output_tokens"] = int(raw.strip().replace(",", ""))
                        break
                    except ValueError:
                        self.console.print(f"[{ERROR_RED}]Enter a whole number (e.g. 4096)[/{ERROR_RED}]")

            self.api.create_profile(name, profile)
            self.console.print(f"[{GREEN}]✦ Created profile: {name}[/{GREEN}]")
        except Exception as e:
            self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")

    async def handle_compact(self, chat_id: str) -> None:
        """Trigger manual context compaction."""
        if not chat_id:
            self.console.print(f"[{ERROR_RED}]No active chat session[/{ERROR_RED}]")
            return

        from cli.animation import ParticleSpinner

        spinner = ParticleSpinner(self.console, "Compacting context")
        spinner.start()
        try:
            metadata = await asyncio.to_thread(self.api.compact_chat, chat_id)
        except Exception as e:
            spinner.stop()
            self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")
            return
        spinner.stop()

        tokens_before = metadata.get("tokens_before", 0)
        tokens_after = metadata.get("tokens_after")
        turns_removed = metadata.get("turns_removed", 0)
        msg = Text()
        msg.append("  ✦ Compaction complete", style=f"bold {GREEN}")
        if tokens_after is not None:
            msg.append(
                f"  {tokens_before:,} → {tokens_after:,} tokens, {turns_removed} turns summarized",
                style=DIM
            )
        else:
            msg.append(f"  {turns_removed} turns summarized", style=DIM)
        self.console.print(msg)

    def handle_context(self, chat_id: str) -> None:
        """Display context window usage visualization."""
        if not chat_id:
            self.console.print(f"[{ERROR_RED}]No active chat session[/{ERROR_RED}]")
            return
        try:
            info = self.api.get_context_info(chat_id)
        except Exception as e:
            self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")
            return

        current = info["current_tokens"]
        window = info["context_window"]
        threshold = info["compaction_threshold"]

        if not window:
            self.console.print(f"[{WARN_AMBER}]No context window configured for this model[/{WARN_AMBER}]")
            return

        pct = current / window
        bar_width = min(self.console.width - 4, 60)
        filled = int(pct * bar_width)
        filled = min(filled, bar_width)
        threshold_pos = int(threshold * bar_width)

        # Color: green below threshold, amber up to 90%, red above
        if pct < threshold:
            fill_color = GREEN
        elif pct < 0.90:
            fill_color = WARN_AMBER
        else:
            fill_color = ERROR_RED

        # Build the bar character by character
        bar = Text()
        for i in range(bar_width):
            if i == threshold_pos:
                # Compaction marker — always visible
                bar.append("│", style=f"bold {PURPLE_BOLD}")
            elif i < filled:
                bar.append("█", style=fill_color)
            else:
                bar.append("░", style=DIM)

        # Header
        header = Text()
        header.append("  ⊹ ", style=PURPLE_BOLD)
        header.append("Context Window", style=f"bold {PURPLE_BOLD}")
        self.console.print(header)

        # Bar
        bar_line = Text("  ")
        bar_line.append_text(bar)
        self.console.print(bar_line)

        # Stats line
        stats = Text("  ")
        stats.append(f"{current:,}", style=f"bold {fill_color}")
        stats.append(f" / {window:,} tokens", style=DIM)
        stats.append(f"  ({pct:.0%})", style=f"bold {fill_color}")
        self.console.print(stats)

        # Threshold label positioned under the marker
        label = f"▲ {threshold:.0%} auto-compact"
        pad = max(2 + threshold_pos - len(label) // 2, 2)
        marker_line = Text(" " * pad)
        marker_line.append(label, style=PURPLE)
        self.console.print(marker_line)

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
                panel_content += f"[{DIM}]No tool overrides[/{DIM}]"

            self.console.print(Panel(
                panel_content,
                title=f"[bold {GREEN}]Permissions[/bold {GREEN}]",
                border_style=PURPLE,
            ))
        except Exception as e:
            self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")

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
            self.console.print(f"[{ERROR_RED}]Invalid permission command[/{ERROR_RED}]")
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
            self.console.print(f"[{ERROR_RED}]Invalid level: {level}[/{ERROR_RED}]")
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
            self.console.print(f"[{GREEN}]✦ Set {tool_name} → {level}[/{GREEN}]")
        except Exception as e:
            error_msg = str(e)
            self.console.print(f"[{ERROR_RED}]Error: {error_msg}[/{ERROR_RED}]")

            # If it's an invalid tool name error, show available tools
            if "Invalid tool name" in error_msg or "400" in error_msg:
                try:
                    tools = self.api.get_available_tools()
                    self.console.print(f"[{WARN_AMBER}]Available tools: {', '.join(tools)}[/{WARN_AMBER}]")
                except Exception:
                    pass

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
                self.console.print(f"[{WARN_AMBER}]No override set for: {tool_name}[/{WARN_AMBER}]")
                return

            # Remove the override
            del overrides[tool_name]

            # Save back
            self.api.update_permissions(perms.get("mode"), overrides)
            self.console.print(f"[{GREEN}]✦ Cleared override for {tool_name}[/{GREEN}]")
        except Exception as e:
            self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")

    async def set_permission_mode(self, mode: str):
        """Set global permission mode.

        Args:
            mode: Permission mode (interactive/autonomous/readonly)
        """
        valid_modes = ["interactive", "autonomous", "readonly"]
        if mode not in valid_modes:
            self.console.print(f"[{ERROR_RED}]Invalid mode: {mode}[/{ERROR_RED}]")
            self.console.print(f"Must be one of: {', '.join(valid_modes)}")
            return

        try:
            # Get current permissions to preserve overrides
            perms = self.api.get_permissions()
            overrides = perms.get("tool_overrides", {})

            # Update mode
            self.api.update_permissions(mode, overrides)
            self.console.print(f"[{GREEN}]✦ Set mode to: {mode}[/{GREEN}]")
        except Exception as e:
            self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")

    def list_chats(self):
        """Display chat list as table."""
        try:
            chats = self.api.list_chats()

            if not chats:
                self.console.print(f"[{WARN_AMBER}]No chats found[/{WARN_AMBER}]")
                return

            table = Table(title="Chat Sessions", border_style=PURPLE)
            table.add_column("Chat ID", style=GREEN)

            for chat in chats:
                table.add_row(chat["chat_id"])

            self.console.print(table)
        except Exception as e:
            self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")

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
                self.console.print(f"[{GREEN}]Created new chat: {chat_id}[/{GREEN}]")
                return chat_id
            except Exception as e:
                self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")
                return None
        else:
            # Treat the argument as a chat ID to switch to
            chat_id = subcommand
            try:
                chats = self.api.list_chats()
                chat_ids = [c["chat_id"] for c in chats]
                if chat_id not in chat_ids:
                    self.console.print(f"[{ERROR_RED}]Chat not found: {chat_id}[/{ERROR_RED}]")
                    return None
                self.console.print(f"[{GREEN}]Switched to chat: {chat_id}[/{GREEN}]")
                return chat_id
            except Exception as e:
                self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")
                return None

    def handle_sandbox(self, args: list[str]) -> None:
        """Handle sandbox subcommands.

        Args:
            args: Command arguments
        """
        if not args:
            try:
                enabled = self.api.get_sandbox()
                state = f"[{GREEN}]enabled[/{GREEN}]" if enabled else f"[{WARN_AMBER}]disabled[/{WARN_AMBER}]"
                self.console.print(f"Sandbox: {state}")
            except Exception as e:
                self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")
            return

        subcommand = args[0]
        if subcommand == "on":
            try:
                self.api.set_sandbox(True)
                self.console.print(f"[{GREEN}]Sandbox enabled[/{GREEN}]")
            except Exception as e:
                self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")
        elif subcommand == "off":
            try:
                self.api.set_sandbox(False)
                self.console.print(f"[{WARN_AMBER}]Sandbox disabled[/{WARN_AMBER}]")
            except Exception as e:
                self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")
        elif subcommand == "build":
            try:
                self.console.print(f"[{DIM}]Building sandbox image (this may take a few minutes)...[/{DIM}]")
                self.api.build_sandbox()
                self.console.print(f"[{GREEN}]Sandbox image built successfully[/{GREEN}]")
            except Exception as e:
                self.console.print(f"[{ERROR_RED}]Error: {e}[/{ERROR_RED}]")
        else:
            self.console.print(f"[{ERROR_RED}]Invalid sandbox command[/{ERROR_RED}]")
            self.console.print("Usage: /sandbox [on|off|build]")
