from agent.models.tool import Tool
from agent.tools.functions.bash import bash_func


bash_tool = Tool(
  name="bash",
  description="Execute a shell command. Use for system commands, searches (find, grep, ls), git, and package management. Do NOT use for file I/O — use the read, write, or edit tools instead of cat, echo, sed, or heredoc redirection.",
  parameters={
    "type": "object",
    "properties": {
      "command": {
        "type": "string",
        "description": "The bash command to execute"
      },
      "timeout": {
        "type": "integer",
        "description": "Max execution time in seconds (default 60, max 300). Increase for long-running commands like transcription or builds."
      }
    },
    "required": ["command"]
  },
  func=bash_func
)