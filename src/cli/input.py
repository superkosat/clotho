"""Async input handling with escape-to-cancel for Clotho CLI."""

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings

from cli.theme import GREEN


class CancelledInput(Exception):
    """Raised when the user presses Escape to cancel input."""
    pass


class ClothoInput:
    """Input handler with escape-to-cancel and styled prompt.

    Uses prompt_toolkit for async input with key binding support.
    Shows "(esc to cancel)" as a bottom toolbar hint that disappears
    after submission. Pressing Escape on an empty buffer cancels;
    with text it clears first.
    """

    def __init__(self):
        self._bindings = KeyBindings()
        self._setup_bindings()
        self._session = PromptSession(key_bindings=self._bindings)

    def _setup_bindings(self):
        """Configure escape key to cancel."""

        @self._bindings.add("escape", eager=True)
        def _escape(event):
            buf = event.current_buffer
            if buf.text:
                # First press clears the buffer
                buf.text = ""
                buf.cursor_position = 0
            else:
                # Second press (or press on empty buffer) cancels
                event.app.exit(exception=CancelledInput())

    async def prompt(self) -> str:
        """Get user input with escape-to-cancel support.

        Returns:
            The user's input string

        Raises:
            CancelledInput: If the user pressed Escape
            EOFError: If EOF is received
        """
        prompt_text = FormattedText([(f"bold {GREEN}", "> ")])
        return await self._session.prompt_async(prompt_text)

    async def confirm(self, prompt_text: str = "Approve tools? (y/n):") -> str:
        """Get a confirmation input without the escape hint.

        Args:
            prompt_text: The confirmation prompt

        Returns:
            The user's response
        """
        formatted = FormattedText([(GREEN, prompt_text + " ")])
        return await self._session.prompt_async(formatted)
