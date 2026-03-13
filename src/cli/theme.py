"""Clotho CLI theme - green and purple color palette."""

from rich.theme import Theme

# Core palette
GREEN = "#7fdb8a"       # Primary green - soft mint
GREEN_DIM = "#4a9e54"   # Dimmed green
GREEN_BOLD = "#a0f0ab"  # Bright green for emphasis
PURPLE = "#b48ead"      # Primary purple - muted lavender
PURPLE_DIM = "#8a6d96"  # Dimmed purple
PURPLE_BOLD = "#d4a6e8" # Bright purple for emphasis
SURFACE = "#2e2e3e"     # Dark surface for panels
ERROR_RED = "#e06c75"   # Softer red for errors
WARN_AMBER = "#d4a347"  # Warm amber for warnings
DIM = "#6c6c8a"         # Muted text

# Rich markup shortcuts
ACCENT = f"[{GREEN}]"
ACCENT_END = f"[/{GREEN}]"
HIGHLIGHT = f"[bold {GREEN}]"
HIGHLIGHT_END = f"[/bold {GREEN}]"
SECONDARY = f"[{PURPLE}]"
SECONDARY_END = f"[/{PURPLE}]"
SEC_BOLD = f"[bold {PURPLE}]"
SEC_BOLD_END = f"[/bold {PURPLE}]"
ERR = f"[{ERROR_RED}]"
ERR_END = f"[/{ERROR_RED}]"
WARN = f"[{WARN_AMBER}]"
WARN_END = f"[/{WARN_AMBER}]"
MUTED = f"[{DIM}]"
MUTED_END = f"[/{DIM}]"

# Rich Theme instance for Console
CLOTHO_THEME = Theme({
    "accent": GREEN,
    "accent.bold": f"bold {GREEN_BOLD}",
    "secondary": PURPLE,
    "secondary.bold": f"bold {PURPLE_BOLD}",
    "info": PURPLE_DIM,
    "success": GREEN,
    "error": ERROR_RED,
    "warning": WARN_AMBER,
    "muted": DIM,
    "prompt": f"bold {GREEN}",
    "prompt.hint": DIM,
    "tool": PURPLE,
    "tool.name": f"bold {PURPLE_BOLD}",
})

