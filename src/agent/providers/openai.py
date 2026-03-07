import json
from collections.abc import Iterator

from agent.LLM import LLM
from agent.models.tool import Tool
from agent.models.turn import AssistantTurn, Turn
from agent.models.content_block import ImageContent, TextContent, ToolUseContent, ToolResultContent
from agent.models.usage import Usage
import openai

class OpenAIModel(LLM):
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
    ):
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.client = openai.Client(
            base_url=base_url,
            api_key=api_key
        )

    def stream_invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int) -> Iterator[str]:
        openai_messages = self._to_openai_messages(messages)

        if tools:
            tools = self._convert_tools(tools)

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            tools=tools,
            max_tokens=max_tokens,
            stream=True,
        )
        
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content

    def invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int) -> AssistantTurn:
        openai_messages = self._to_openai_messages(messages)

        if tools:
            tools = self._convert_tools(tools)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=openai_messages,
            tools=tools,
            max_tokens=max_tokens,
        )

        return self._to_assistant_turn(response)

    def _to_openai_messages(self, turns: list[Turn]) -> list[dict]:
        messages = []
        for turn in turns:
            if isinstance(turn.content, str):
                messages.append({"role": turn.role, "content": turn.content})
            else:
                texts = []
                images = []
                tool_calls = []
                tool_results = []

                for block in turn.content:
                    if isinstance(block, TextContent):
                        texts.append(block.text)
                    elif isinstance(block, ImageContent):
                        if block.source_type == "base64":
                            images.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{block.media_type};base64,{block.data}"
                                }
                            })
                        else:
                            images.append({
                                "type": "image_url",
                                "image_url": {"url": block.data}
                            })
                    elif isinstance(block, ToolUseContent):
                        tool_calls.append({
                            "id": block.id,
                            "type": "function",
                            "function": {
                                "name": block.name,
                                "arguments": json.dumps(block.arguments)
                            }
                        })
                    elif isinstance(block, ToolResultContent):
                        tool_results.append(block)

                if images:
                    content_parts = [{"type": "text", "text": "\n".join(texts)}] + images
                    messages.append({"role": turn.role, "content": content_parts})
                elif texts or tool_calls:
                    msg = {"role": turn.role, "content": "\n".join(texts) or None}
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    messages.append(msg)

                for result in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": result.tool_use_id,
                        "content": result.content
                    })

        return messages

    def _to_assistant_turn(self, response) -> AssistantTurn:
        message = response.choices[0]
        content: str | list = message.message.content or ""
        finish_reason = message.finish_reason

        if finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif finish_reason == "length":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"

        if message.message.tool_calls:
            stop_reason = "tool_use"
            content_blocks = []

            if message.message.content:
                content_blocks.append(TextContent(text=message.message.content))

            for tool_call in message.message.tool_calls:
                content_blocks.append(ToolUseContent(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=json.loads(tool_call.function.arguments)
                ))

            content = content_blocks

        return AssistantTurn(
            content=content,
            model=response.model,
            stop_reason=stop_reason,
            usage=Usage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens
            )
        )


    def _convert_tools(self, tools: list[Tool]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            }
            for tool in tools
        ]
    
    def compact(self):
        pass
