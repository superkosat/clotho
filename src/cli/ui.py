"""Shared UI primitives for Clotho CLI."""

from contextlib import asynccontextmanager

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from cli.theme import DIM, ERROR_RED, GREEN, PURPLE, PURPLE_BOLD, WARN_AMBER


LOADING_PHRASES = [
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


# ── Print helpers ─────────────────────────────────────────────────────────────

def print_error(console: Console, msg: str) -> None:
    console.print(f"[{ERROR_RED}]{msg}[/{ERROR_RED}]")


def print_success(console: Console, msg: str) -> None:
    t = Text()
    t.append("  ● ", style=f"bold {GREEN}")
    t.append(msg, style=GREEN)
    console.print(t)


def print_warning(console: Console, msg: str) -> None:
    console.print(f"[{WARN_AMBER}]{msg}[/{WARN_AMBER}]")


def print_muted(console: Console, msg: str) -> None:
    console.print(f"[{DIM}]{msg}[/{DIM}]")


def print_header(console: Console, msg: str) -> None:
    t = Text()
    t.append("  ⊹ ", style=PURPLE_BOLD)
    t.append(msg, style=f"bold {PURPLE_BOLD}")
    console.print(t)


def styled_panel(console: Console, content: str, title: str) -> None:
    console.print(Panel(
        content,
        title=f"[bold {GREEN}]{title}[/bold {GREEN}]",
        border_style=PURPLE,
    ))


# ── Spinner context manager ───────────────────────────────────────────────────

@asynccontextmanager
async def spinner_context(console: Console, label: str):
    """Async context manager that shows a ParticleSpinner for the duration."""
    from cli.animation import ParticleSpinner
    spinner = ParticleSpinner(console, label)
    spinner.start()
    try:
        yield spinner
    finally:
        spinner.stop()
