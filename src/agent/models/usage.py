from pydantic import BaseModel

class Usage(BaseModel):
    input_tokens: int
    output_tokens: int