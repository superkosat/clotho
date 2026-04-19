# REST API

The gateway exposes a REST + WebSocket API on `http://127.0.0.1:8000`. All endpoints except `/health` require the `Authorization: Bearer <token>` header.

## Health

```
GET /health
```

Returns `200 OK` when the gateway is running. No auth required.

## Chats

```
POST   /api/chats                    Create a new chat session
GET    /api/chats                    List all chat sessions
DELETE /api/chats/{chat_id}          Delete a chat session
GET    /api/chats/{chat_id}/context  Get context token usage
POST   /api/chats/{chat_id}/compact  Manually compact context
```

## Agent

```
WebSocket /ws/{chat_id}?token=<token>
```

Connect to run agent turns. Send JSON messages, receive streamed events.

**Send:**
```json
{ "type": "user_message", "content": "what files are here?", "stream": true }
```

**Receive events:**

| Event | Payload |
|---|---|
| `agent.text_delta` | `{ "text": "..." }` — streaming text chunk |
| `agent.text` | `{ "text": "..." }` — complete text (non-streaming) |
| `agent.tool_request` | `{ "tool_calls": [...] }` — approval required |
| `agent.tool_result` | `{ "tool_use_id", "tool_name", "content", "is_error" }` |
| `agent.turn_complete` | `{ "stop_reason", "model", "usage" }` |
| `agent.error` | `{ "message": "..." }` |
| `agent.compaction_started` | `{ "tokens_before", "context_window" }` |
| `agent.context_compacted` | `{ "tokens_before", "tokens_after", "turns_removed" }` |

**Approve tool calls:**
```json
{ "type": "tool_approval", "verdicts": { "<tool_use_id>": "allow" } }
```

## Profiles

```
GET    /api/profiles              List profiles and default
POST   /api/profiles              Create a profile
DELETE /api/profiles/{name}       Delete a profile
GET    /api/profiles/default      Get default profile name
PUT    /api/profiles/default      Set default profile
GET    /api/chats/{id}/profile    Get active profile for a chat
PUT    /api/chats/{id}/profile    Switch profile for a chat
```

## Permissions

```
GET  /api/permissions             Get current permissions
PUT  /api/permissions             Update permissions
GET  /api/permissions/tools       List available tool names
```

## Config

```
GET  /api/config/sandbox          Get sandbox config
PUT  /api/config/sandbox          Update sandbox config
```
