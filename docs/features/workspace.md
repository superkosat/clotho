# Workspace & Identity Files

Clotho maintains three Markdown files in `~/.clotho/workspace/` that define who the agent is,
what it knows about you, and what it remembers about ongoing work. These files are read at the
start of every session and updated over time as the agent learns.

```
~/.clotho/workspace/
    PERSONALITY.md   # the agent's identity and character
    USER.md          # persistent knowledge about you
    AGENTS.md        # ongoing work, decisions, and context
```

These files are created automatically the first time you run `clotho setup`.

---

## PERSONALITY.md

This file defines the agent's character — its tone, values, and way of engaging. The agent reads
it at the start of every session and is instructed to *be* the personality described, not just
note it.

A default personality is written on first setup. It is intentionally opinionated: direct, witty,
collaborative, and intolerant of slop. You can edit it freely to shape how the agent feels to
work with.

The agent will update this file on its own, but only sparingly — only when clear, recurring
patterns across many sessions suggest a genuine refinement. It will never update it based on a
single session.

**Edit this file directly** to change the agent's character at any time. The change takes effect
on the next session.

---

## USER.md

This file is the agent's persistent memory of you. It stores anything meaningful the agent has
learned across sessions: your name, profession, preferences, working style, recurring concerns,
things you care about.

At the start of each session the agent reads this file so it can engage with you as someone it
knows rather than a stranger. Over time it builds up a picture of who you are and adjusts
accordingly.

The agent updates USER.md during sessions when something meaningful surfaces — not after every
message, but when something genuinely worth remembering comes up. It reads the file first and
makes targeted additions; it never overwrites existing content.

**You can edit this file directly** to add, correct, or remove anything.

---

## AGENTS.md

This file holds persistent context about ongoing work: active projects, decisions made,
constraints discovered, tasks left mid-flight, and anything else the agent should carry forward
into the next session.

Think of it as a handoff note the agent writes to itself. At the end of a session where
significant work happened, the agent updates this file so the next session can pick up where it
left off without re-deriving context.

The agent keeps this file current — stale entries are removed as projects evolve.

**You can edit this file directly** to add context, correct the record, or clean up old entries.

---

## How the System Prompt Is Built

Clotho assembles the system prompt dynamically at the start of each session. The core prompt
defines the agent's capabilities and rules. On top of that, several sections are injected:

```
[Core prompt]
    ↓
[Today's date]
    ↓
[Environment info]          ← working directory, platform, detected project tooling
    ↓
[Additional tools]          ← registered MCP tools (name + description only)
    ↓
[Project context]           ← custom rules from config, if set
    ↓
[Skills]                    ← name + description of each skill in ~/.clotho/skills/
```

The workspace files (`PERSONALITY.md`, `USER.md`, `AGENTS.md`) are **not injected** into the
prompt. Instead, the core prompt instructs the agent to read them using the `read` tool as its
very first action each session. This keeps the prompt lean while still giving the agent full
access to their contents.

### Why not inject them?

Injecting the files would mean their content is baked into the prompt at session start and never
refreshed within a session. Reading them with a tool call means:

- The agent gets the live file contents (including any edits you made mid-session)
- The context window isn't pre-loaded with potentially stale content
- The agent can re-read a file mid-session if it needs to update it and verify the result

### Skills vs Workspace Files

| | Skills | Workspace files |
|---|---|---|
| Purpose | Task-specific instructions | Identity, memory, context |
| Injected into prompt | Name + description only | Not injected — read on demand |
| Updated by | You | The agent (and you) |
| Scope | Per-task | Persistent across sessions |
