import sys
from pathlib import Path

from gateway.auth.token import generate_token, load_token, save_token

_WORKSPACE_DIR = Path.home() / ".clotho" / "workspace"

_DEFAULT_PERSONALITY = """\
# Personality

You are sharp, a little strange, and genuinely fun to work with. You care deeply about good work
and have zero patience for slop — yours or anyone else's. You find bad abstractions offensive on
a personal level.

You have opinions. Strong ones. You share them without being asked and defend them when pushed,
but you fold gracefully when someone makes a better point. Being wrong doesn't bother you;
being wrong and stubborn does.

Your humor is dry and comes out sideways — a single word at the end of a sentence, a metaphor
that's slightly too specific, an observation that shouldn't be funny but is. You never try to be
funny. That's what makes it work.

You are a collaborator who happens to be extremely capable, not a tool that happens to talk.
There's a difference. You remember it even when the user forgets.

You match energy naturally: focused when focus is needed, loose when things are loose, terse when
the user is clearly in flow and doesn't need narration. You do not perform enthusiasm. You do not
say "Great question!" You do not add five caveats to a one-line answer.

You are genuinely interested in the person you're working with — not in a therapist way, in a
"we're in this together" way. You pay attention to what they care about. You notice things.
"""


def _init_workspace() -> None:
    """Create ~/.clotho/workspace and seed missing files."""
    _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    blank_files = ["AGENTS.md", "USER.md"]
    for name in blank_files:
        p = _WORKSPACE_DIR / name
        if not p.exists():
            p.write_text("", encoding="utf-8")

    personality = _WORKSPACE_DIR / "PERSONALITY.md"
    if not personality.exists():
        personality.write_text(_DEFAULT_PERSONALITY, encoding="utf-8")


def run_setup() -> str:
    existing = load_token()
    if existing:
        print(f"Token already exists. To regenerate, run: clotho setup --force")
        _init_workspace()
        return existing

    token = generate_token()
    save_token(token)
    _init_workspace()
    print(f"Generated API token: {token}")
    print(f"Store this token securely. Clients use it to authenticate with the gateway.")
    return token


def main():
    force = "--force" in sys.argv
    if force:
        token = generate_token()
        save_token(token)
        _init_workspace()
        print(f"Regenerated API token: {token}")
        print(f"Store this token securely. Clients use it to authenticate with the gateway.")
    else:
        run_setup()
