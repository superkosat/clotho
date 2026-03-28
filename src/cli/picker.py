"""Inline arrow-key picker component for Clotho CLI.

Thin wrapper around questionary.select that applies Clotho's theme
and provides a consistent API across all interactive flows.
"""

import questionary
from questionary import Style

from cli.theme import DIM, ERROR_RED, GREEN, PURPLE_BOLD, WARN_AMBER


# Map questionary token names to Clotho theme colors
CLOTHO_SELECT_STYLE = Style([
    ("qmark",          f"bold {PURPLE_BOLD}"),   # the ? marker
    ("question",       f"bold {PURPLE_BOLD}"),   # question text
    ("answer",         f"bold {GREEN}"),          # selected answer (after confirm)
    ("pointer",        f"bold {GREEN}"),          # ▶ cursor
    ("highlighted",    f"bold {GREEN}"),          # focused option
    ("selected",       GREEN),                    # checked item (checkbox)
    ("separator",      DIM),
    ("instruction",    DIM),                      # (Use arrow keys)
    ("text",           ""),
])


class PickerCancelled(Exception):
    """Raised when the user presses Escape to dismiss the picker."""


async def pick(
    question: str,
    options: list[tuple[str, str]],
) -> str:
    """Show an inline arrow-key single-select picker.

    Args:
        question: Prompt text shown above the list.
        options:  List of ``(value, label)`` pairs.  ``value`` is returned;
                  ``label`` is displayed.

    Returns:
        The value of the chosen option.

    Raises:
        PickerCancelled: If the user pressed Escape or Ctrl-C.
    """
    choices = [
        questionary.Choice(title=label, value=value)
        for value, label in options
    ]
    result = await questionary.select(
        question,
        choices=choices,
        style=CLOTHO_SELECT_STYLE,
        qmark="∟",
        use_shortcuts=False,
        use_arrow_keys=True,
        instruction="",
    ).ask_async()

    if result is None:
        raise PickerCancelled()
    return result


async def pick_many(
    question: str,
    options: list[tuple[str, str]],
) -> list[str]:
    """Show an inline checkbox multi-select picker.

    Args:
        question: Prompt text shown above the list.
        options:  List of ``(value, label)`` pairs.

    Returns:
        List of selected values (may be empty).

    Raises:
        PickerCancelled: If the user pressed Escape or Ctrl-C.
    """
    choices = [
        questionary.Choice(title=label, value=value)
        for value, label in options
    ]
    result = await questionary.checkbox(
        question,
        choices=choices,
        style=CLOTHO_SELECT_STYLE,
        qmark="⊹",
        instruction="",
    ).ask_async()

    if result is None:
        raise PickerCancelled()
    return result
