# Clotho

An agentic harness with a central gateway architecture. Clotho runs a local server that manages agent sessions, tool execution, and model routing. Interact with it through the terminal REPL, Discord, scheduled jobs, or build your own client against the REST/WebSocket API.

## Quick Start

```bash
pipx install git+https://github.com/superkosat/clotho.git
clotho setup    # generate auth token
clotho          # start gateway + REPL
```

Then configure a model profile:

```
/profile add
/profile default <name>
```

## Architecture

```mermaid
flowchart TB
    subgraph clients[Clients]
        REPL[Terminal REPL] ~~~ Discord[Discord Bridge] ~~~ Scheduler[Scheduler] ~~~ Custom[Custom Client]
    end

    clients -->|REST + WebSocket| gw

    subgraph gw[Gateway]
        direction LR
        SM[Session Manager]
        Auth[Auth]
    end

    gw --> Agent[Agent Core]
    gw --> Tools[Built-in Tools\nbash · read · write · edit]
    gw --> MCP[MCP Servers\nstdio · streamable_http]
```

The gateway is the single point of entry. All clients — the terminal REPL, Discord bridge, scheduler, or your own code — connect over HTTP/WebSocket using a shared auth token.
