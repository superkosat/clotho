from agent.models.tool import Tool
from agent.tools.functions.write import write_func


write_tool = Tool(
  name="write",
  description="Create a new file or overwrite/append to an existing file. Always use this instead of bash with cat, echo, or heredoc to create files.",
  parameters={
    "type": "object",
    "properties": {
      "file_path": {
        "type": "string",
        "description": "The absolute path to the file to write"
      },
      "content": {
        "type": "string",
        "description": "The content to write to the file"
      },
      "mode": {
        "type": "string",
        "enum": ["w", "a"],
        "description": "The file write mode ('w' for overwrite, 'a' for append)",
        "default": "w"
      }
    },
    "required": ["file_path", "content"]
  },
  func=write_func
)