"""
Skills loader — reads skill definitions from ~/.clotho/skills/.

Each skill lives in its own subdirectory containing a SKILL.md file and
optionally any supporting scripts or assets:

    ~/.clotho/skills/
        commit/
            SKILL.md
            commit.sh      (optional)
        review-pr/
            SKILL.md
            helpers.py     (optional)

Only SKILL.md is parsed. Its frontmatter metadata is injected into the system
prompt; the full body stays on disk. When the agent decides a skill applies,
it reads SKILL.md at the path provided in <location>.

Frontmatter format:

    ---
    name: commit
    description: Use when the user asks to commit or stage changes to git.
    ---

    <full skill instructions — only loaded on demand by the agent>
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

SKILLS_DIR = Path.home() / ".clotho" / "skills"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_KV_RE = re.compile(r"^(\w+)\s*:\s*(.+)$", re.MULTILINE)


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    extra: dict = field(default_factory=dict)


def _parse_skill_file(path: Path) -> Skill:
    """Parse a single skill file — reads only frontmatter metadata."""
    raw = path.read_text(encoding="utf-8")

    match = _FRONTMATTER_RE.match(raw)
    if match:
        meta = {k: v.strip() for k, v in _KV_RE.findall(match.group(1))}
    else:
        meta = {}

    name = meta.pop("name", path.parent.name)
    description = meta.pop("description", "")

    return Skill(name=name, description=description, path=path, extra=meta)


def load_skills(skills_dir: Optional[Path] = None) -> list[Skill]:
    """
    Load skill metadata from *skills_dir* (defaults to ~/.clotho/skills/).
    Only frontmatter is parsed; skill bodies remain on disk.
    Returns an empty list if the directory does not exist.
    """
    directory = skills_dir or SKILLS_DIR
    if not directory.is_dir():
        return []

    skills: list[Skill] = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if skill_file.is_file():
            try:
                skills.append(_parse_skill_file(skill_file))
            except Exception:
                pass  # Skip unreadable / malformed skill files

    return skills


def build_skills_prompt_section(skills: list[Skill]) -> str:
    """
    Render skill metadata into a compact XML block for the system prompt.
    Only name, description, trigger, and file location are included — the
    full instructions stay on disk and are read by the agent on demand.

    Example output:

        <available_skills>
        <skill>
        <name>commit</name>
        <description>Stage and commit changes with a conventional commit message.</description>
        <trigger>When the user asks to commit, stage, or save changes to git.</trigger>
        <location>/home/user/.clotho/skills/commit.md</location>
        </skill>
        </available_skills>
    """
    if not skills:
        return ""

    parts = ["<available_skills>"]
    for skill in skills:
        parts.append("<skill>")
        parts.append(f"<name>{skill.name}</name>")
        if skill.description:
            parts.append(f"<description>{skill.description}</description>")
        parts.append(f"<location>{skill.path}</location>")
        parts.append("</skill>")
    parts.append("</available_skills>")

    return "\n".join(parts)
