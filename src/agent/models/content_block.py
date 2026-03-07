from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field

class TextContent(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ImageContent(BaseModel):
    type: Literal["image"] = "image"
    source_type: Literal["base64", "url"]
    media_type: str | None = None #"img/png"
    data: str #base64 string or url

class ToolUseContent(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    arguments: dict

class ToolResultContent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    tool_name: str  # Needed for providers like Ollama that match by name
    content: str
    is_error: bool = False

ContentBlock = Annotated[
    Union[TextContent, ImageContent, ToolUseContent, ToolResultContent],
    Field(discriminator="type")
]