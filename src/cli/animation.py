"""Animated spinner for Clotho CLI loading states."""

import asyncio

from rich.console import Console
from rich.live import Live
from rich.text import Text

from cli.theme import GREEN, PURPLE

# Braille dot spinner frames — all same width, smooth rotation.
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class ParticleSpinner:
    """Single cycling spinner with status label, left-aligned.

    Renders like:  ⠹ Thinking
    Uses Rich's Live display for flicker-free updates.
    """

    def __init__(self, console: Console, label: str = "Thinking"):
        self.console = console
        self.label = label
        self._running = False
        self._task: asyncio.Task | None = None
        self._live: Live | None = None
        self._frame = 0

    def _render_frame(self) -> Text:
        """Render the spinner line: cycling dot + label."""
        char = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
        text = Text()
        text.append(f" {char} ", style=PURPLE)
        text.append(self.label, style=f"bold {GREEN}")
        return text

    async def _animate(self):
        """Main animation loop using Rich Live for smooth updates."""
        self._live = Live(
            self._render_frame(),
            console=self.console,
            refresh_per_second=12,
            transient=True,
        )
        self._live.start()
        try:
            while self._running:
                self._frame += 1
                self._live.update(self._render_frame())
                await asyncio.sleep(0.08)
        finally:
            if self._live:
                self._live.stop()
                self._live = None

    def start(self):
        """Start the spinner animation."""
        self._running = True
        self._task = asyncio.create_task(self._animate())

    def stop(self):
        """Stop the spinner animation."""
        self._running = False
        if self._live:
            self._live.stop()
            self._live = None
        if self._task:
            self._task.cancel()
            self._task = None

    def update_label(self, label: str):
        """Update the displayed status label."""
        self.label = label
