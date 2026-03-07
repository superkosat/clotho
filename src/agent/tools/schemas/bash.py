from agent.models.tool import Tool
from agent.tools.functions.bash import bash_func


bash_tool = Tool(
  name="bash",
  description="Execute a unix bash command on the machine",
  parameters={
    "type": "object",
    "properties": {
      "command": {
        "type": "string",
        "description": "The bash command to execute"
      }
    },
    "required": ["command"]
  },
  func=bash_func
)