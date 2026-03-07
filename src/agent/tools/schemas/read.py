from agent.models.tool import Tool
from agent.tools.functions.read import read_func


read_tool = Tool(
  name="read",
  description="Read the contents of a text file or image file. Requires an absolute file path. Returns up to 100 lines at a time for text files. Use start_line and end_line to read specific sections of large files.",
  parameters={
    "type": "object",
    "properties": {
      "file_path": {
        "type": "string",
        "description": "The absolute path to the file to read"
      },
      "start_line": {
        "type": "integer",
        "description": "The line number to start reading from (1-indexed, default: 1)"
      },
      "end_line": {
        "type": "integer",
        "description": "The line number to stop reading at (inclusive)"
      }
    },
    "required": ["file_path"]
  },
  func=read_func
)
