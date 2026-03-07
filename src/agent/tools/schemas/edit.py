from agent.models.tool import Tool
from agent.tools.functions.edit import edit_func


edit_tool = Tool(
  name="edit",
  description="Edit the contents of a text file by providing the old section to replace, and the new section to be written in its place. Requires an absolute file path.",
  parameters={
    "type": "object",
    "properties": {
      "file_path": {
        "type": "string",
        "description": "The absolute path to the file to edit"
      },
      "old_string": {
        "type": "string",
        "description": "The string representing the old content to replace"
      },
      "new_string": {
        "type": "string",
        "description": "The string containing the new content to be written over the old string"
      },
      "replace_all": {
        "type": "boolean",
        "description": "Whether or not to replace all occurrences of the old string. Helpful for bulk edit operations in one file."
      }
    },
    "required": ["file_path", "old_string", "new_string"]
  },
  func=edit_func
)