"""Command handlers for REPL slash commands."""

import asyncio

from rich.console import Console
from rich.table import Table
from rich.text import Text

from cli.api_client import ClothoAPIClient
from cli.theme import DIM, ERROR_RED, GREEN, GREEN_BOLD, PURPLE, PURPLE_BOLD, WARN_AMBER
from cli.ui import (
    print_error, print_success, print_warning, print_muted, print_header,
    styled_panel, spinner_context,
)


class CommandHandler:
    """Handles slash commands in REPL."""

    def __init__(self, console: Console, api_client: ClothoAPIClient):
        self.console = console
        self.api = api_client

    def list_profiles(self):
        """Display profiles as table."""
        try:
            data = self.api.list_profiles()
            default = data.get("default")
            profiles = data.get("profiles", {})

            if not profiles:
                print_warning(self.console, "No profiles found")
                return

            table = Table(title="Model Profiles", border_style=PURPLE)
            table.add_column("Name", style=GREEN)
            table.add_column("Provider")
            table.add_column("Model")
            table.add_column("Default", style=GREEN)

            for name, profile in profiles.items():
                is_default = "✓" if name == default else ""
                table.add_row(
                    name,
                    profile.get("provider", ""),
                    profile.get("model", ""),
                    is_default,
                )

            self.console.print(table)
        except Exception as e:
            print_error(self.console, f"Error: {e}")

    async def handle_profile(self, args: list[str], chat_id: str | None = None):
        """Handle profile subcommands."""
        if not args:
            self.list_profiles()
            return

        subcommand = args[0]

        if subcommand == "add":
            await self.add_profile()
        elif subcommand == "use" and len(args) > 1:
            profile_name = args[1]
            if not chat_id:
                print_error(self.console, "No active chat session")
                return
            try:
                self.api.set_active_profile(chat_id, profile_name)
                print_success(self.console, f"Switched to profile: {profile_name}")
            except Exception as e:
                print_error(self.console, f"Error: {e}")
        elif subcommand == "default" and len(args) > 1:
            profile_name = args[1]
            try:
                self.api.set_default_profile(profile_name)
                print_success(self.console, f"Set default profile: {profile_name}")
            except Exception as e:
                print_error(self.console, f"Error: {e}")
        else:
            print_error(self.console, "Invalid profile command")
            self.console.print("Usage: /profile [add|use <name>|default <name>]")

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

            registry_entry = lookup_model(model)
            if registry_entry:
                profile["context_window"] = registry_entry["context_window"]
                profile["max_output_tokens"] = registry_entry["max_output_tokens"]
            else:
                print_warning(self.console, f"Model '{model}' is not in the known model registry.")
                print_warning(
                    self.console,
                    "You must specify the context window. "
                    "An inaccurate value may break the agent unexpectedly.",
                )
                while True:
                    raw = await asyncio.to_thread(
                        self.console.input, "Context window (tokens, required): "
                    )
                    try:
                        profile["context_window"] = int(raw.strip().replace(",", ""))
                        break
                    except ValueError:
                        print_error(self.console, "Enter a whole number (e.g. 8192)")

                while True:
                    raw = await asyncio.to_thread(
                        self.console.input, "Max output tokens (tokens, required): "
                    )
                    try:
                        profile["max_output_tokens"] = int(raw.strip().replace(",", ""))
                        break
                    except ValueError:
                        print_error(self.console, "Enter a whole number (e.g. 4096)")

            self.api.create_profile(name, profile)
            print_success(self.console, f"Created profile: {name}")
        except Exception as e:
            print_error(self.console, f"Error: {e}")

    async def handle_compact(self, chat_id: str) -> None:
        """Trigger manual context compaction."""
        if not chat_id:
            print_error(self.console, "No active chat session")
            return

        try:
            async with spinner_context(self.console, "Compacting context"):
                metadata = await asyncio.to_thread(self.api.compact_chat, chat_id)
        except Exception as e:
            print_error(self.console, f"Error: {e}")
            return

        tokens_before = metadata.get("tokens_before", 0)
        tokens_after = metadata.get("tokens_after")
        turns_removed = metadata.get("turns_removed", 0)
        msg = Text()
        msg.append("● Compaction complete", style=f"bold {GREEN}")
        if tokens_after is not None:
            msg.append(
                f"  {tokens_before:,} → {tokens_after:,} tokens, {turns_removed} turns summarized",
                style=DIM,
            )
        else:
            msg.append(f"  {turns_removed} turns summarized", style=DIM)
        self.console.print(msg)

    def handle_context(self, chat_id: str) -> None:
        """Display context window usage visualization."""
        if not chat_id:
            print_error(self.console, "No active chat session")
            return
        try:
            info = self.api.get_context_info(chat_id)
        except Exception as e:
            print_error(self.console, f"Error: {e}")
            return

        current = info["current_tokens"]
        window = info["context_window"]
        threshold = info["compaction_threshold"]

        if not window:
            print_warning(self.console, "No context window configured for this model")
            return

        pct = current / window
        bar_width = min(self.console.width - 4, 60)
        filled = min(int(pct * bar_width), bar_width)
        threshold_pos = int(threshold * bar_width)

        if pct < threshold:
            fill_color = GREEN
        elif pct < 0.90:
            fill_color = WARN_AMBER
        else:
            fill_color = ERROR_RED

        bar = Text()
        for i in range(bar_width):
            if i == threshold_pos:
                bar.append("│", style=f"bold {PURPLE_BOLD}")
            elif i < filled:
                bar.append("█", style=fill_color)
            else:
                bar.append("░", style=DIM)

        print_header(self.console, "Context Window")

        bar_line = Text("  ")
        bar_line.append_text(bar)
        self.console.print(bar_line)

        stats = Text("  ")
        stats.append(f"{current:,}", style=f"bold {fill_color}")
        stats.append(f" / {window:,} tokens", style=DIM)
        stats.append(f"  ({pct:.0%})", style=f"bold {fill_color}")
        self.console.print(stats)

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

            content = f"[bold]Mode:[/bold] {mode}\n\n"
            if overrides:
                content += "[bold]Tool Overrides:[/bold]\n"
                for tool, level in overrides.items():
                    content += f"  {tool}: {level}\n"
            else:
                content += f"[{DIM}]No tool overrides[/{DIM}]"

            styled_panel(self.console, content, "Permissions")
        except Exception as e:
            print_error(self.console, f"Error: {e}")

    async def handle_permission(self, args: list[str]):
        """Handle permission subcommands."""
        if not args:
            self.show_permissions()
            return

        subcommand = args[0]

        if subcommand == "set" and len(args) >= 3:
            await self.set_tool_permission(args[1], args[2])
        elif subcommand == "clear" and len(args) >= 2:
            await self.clear_tool_permission(args[1])
        elif subcommand == "mode" and len(args) >= 2:
            await self.set_permission_mode(args[1])
        else:
            print_error(self.console, "Invalid permission command")
            self.console.print("Usage:")
            self.console.print("  /permission                       Show current permissions")
            self.console.print("  /permission set <tool> <level>    Set tool override (allow/ask/deny)")
            self.console.print("  /permission clear <tool>          Clear tool override")
            self.console.print("  /permission mode <mode>           Set mode (interactive/autonomous/readonly)")

    async def set_tool_permission(self, tool_name: str, level: str):
        """Set permission override for a specific tool."""
        valid_levels = ["allow", "ask", "deny"]
        if level not in valid_levels:
            print_error(self.console, f"Invalid level: {level}")
            self.console.print(f"Must be one of: {', '.join(valid_levels)}")
            return

        try:
            perms = self.api.get_permissions()
            overrides = perms.get("tool_overrides", {})
            overrides[tool_name] = level
            self.api.update_permissions(perms.get("mode"), overrides)
            print_success(self.console, f"Set {tool_name} → {level}")
        except Exception as e:
            error_msg = str(e)
            print_error(self.console, f"Error: {error_msg}")
            if "Invalid tool name" in error_msg or "400" in error_msg:
                try:
                    tools = self.api.get_available_tools()
                    print_warning(self.console, f"Available tools: {', '.join(tools)}")
                except Exception:
                    pass

    async def clear_tool_permission(self, tool_name: str):
        """Clear permission override for a specific tool."""
        try:
            perms = self.api.get_permissions()
            overrides = perms.get("tool_overrides", {})
            if tool_name not in overrides:
                print_warning(self.console, f"No override set for: {tool_name}")
                return
            del overrides[tool_name]
            self.api.update_permissions(perms.get("mode"), overrides)
            print_success(self.console, f"Cleared override for {tool_name}")
        except Exception as e:
            print_error(self.console, f"Error: {e}")

    async def set_permission_mode(self, mode: str):
        """Set global permission mode."""
        valid_modes = ["interactive", "autonomous", "readonly"]
        if mode not in valid_modes:
            print_error(self.console, f"Invalid mode: {mode}")
            self.console.print(f"Must be one of: {', '.join(valid_modes)}")
            return

        try:
            perms = self.api.get_permissions()
            overrides = perms.get("tool_overrides", {})
            self.api.update_permissions(mode, overrides)
            print_success(self.console, f"Set mode to: {mode}")
        except Exception as e:
            print_error(self.console, f"Error: {e}")

    def list_chats(self):
        """Display chat list as table."""
        try:
            chats = self.api.list_chats()
            if not chats:
                print_warning(self.console, "No chats found")
                return

            table = Table(title="Chat Sessions", border_style=PURPLE)
            table.add_column("Chat ID", style=GREEN)
            for chat in chats:
                table.add_row(chat["chat_id"])
            self.console.print(table)
        except Exception as e:
            print_error(self.console, f"Error: {e}")

    def handle_chat(self, args: list[str]) -> str | None:
        """Handle chat subcommands. Returns new chat_id if switched, else None."""
        if not args:
            self.list_chats()
            return None

        subcommand = args[0]

        if subcommand == "new":
            try:
                chat_id = self.api.create_chat()
                print_success(self.console, f"Created new chat: {chat_id}")
                return chat_id
            except Exception as e:
                print_error(self.console, f"Error: {e}")
                return None
        else:
            chat_id = subcommand
            try:
                chats = self.api.list_chats()
                chat_ids = [c["chat_id"] for c in chats]
                if chat_id not in chat_ids:
                    print_error(self.console, f"Chat not found: {chat_id}")
                    return None
                print_success(self.console, f"Switched to chat: {chat_id}")
                return chat_id
            except Exception as e:
                print_error(self.console, f"Error: {e}")
                return None

    def handle_sandbox(self, args: list[str]) -> None:
        """Handle sandbox subcommands."""
        if not args:
            try:
                enabled = self.api.get_sandbox()
                state = f"[{GREEN}]enabled[/{GREEN}]" if enabled else f"[{WARN_AMBER}]disabled[/{WARN_AMBER}]"
                self.console.print(f"Sandbox: {state}")
            except Exception as e:
                print_error(self.console, f"Error: {e}")
            return

        subcommand = args[0]
        if subcommand == "on":
            try:
                self.api.set_sandbox(True)
                print_success(self.console, "Sandbox enabled")
            except Exception as e:
                print_error(self.console, f"Error: {e}")
        elif subcommand == "off":
            try:
                self.api.set_sandbox(False)
                print_warning(self.console, "Sandbox disabled")
            except Exception as e:
                print_error(self.console, f"Error: {e}")
        elif subcommand == "build":
            try:
                print_muted(self.console, "Building sandbox image (this may take a few minutes)...")
                self.api.build_sandbox()
                print_success(self.console, "Sandbox image built successfully")
            except Exception as e:
                print_error(self.console, f"Error: {e}")
        else:
            print_error(self.console, "Invalid sandbox command")
            self.console.print("Usage: /sandbox [on|off|build]")
