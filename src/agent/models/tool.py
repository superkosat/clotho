from typing import Any, Callable
from pydantic import BaseModel

{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city and state"
                },
                "unit": {
                    "type": "string", 
                    "enum": ["celsius", "fahrenheit"]
                }
            },
            "required": ["location"]
        }
    }
}

class Tool(BaseModel):
    name: str
    description: str
    parameters: dict
    func: Callable[..., Any]

    class Config:
        arbitrary_types_allowed = True
