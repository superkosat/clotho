# Skills

Skills are prompt-based extensions that teach the agent how to handle specific tasks. They live in `~/.clotho/skills/` and are loaded into the system prompt at session start.

## Directory Structure

```
~/.clotho/skills/
    commit/
        SKILL.md
    review-pr/
        SKILL.md
        helpers.sh    # optional supporting files
```

## SKILL.md Format

```markdown
---
name: commit
description: Stage and commit changes with a conventional commit message.
---

<full instructions for the agent>
```

Only the frontmatter (`name`, `description`) is injected into the system prompt. The full instructions stay on disk and are read by the agent on demand when it determines the skill applies.

## How It Works

1. At session start, Clotho scans `~/.clotho/skills/` for `SKILL.md` files
2. Each skill's `name` and `description` are added to the system prompt
3. When a user request matches a skill's description, the agent reads the full `SKILL.md`
4. The agent follows the skill's instructions for that request

Skills require no code changes and no gateway restart — add a new directory and it's available immediately on the next chat session.
