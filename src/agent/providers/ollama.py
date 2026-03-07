from collections.abc import Iterator

from agent.models.tool import Tool
from agent.models.turn import Turn, AssistantTurn
from agent.models.content_block import TextContent, ImageContent, ToolUseContent, ToolResultContent
from agent.models.usage import Usage
from agent.LLM import LLM
from ollama import chat


class OllamaModel(LLM):
    def __init__(
        self,
        model: str,
    ):
        self.model = model
        self.client = chat

    def stream_invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int) -> Iterator[str]:
        ollama_messages = self._to_ollama_messages(messages)

        if tools:
            tools = self._convert_tools(tools)

        stream = self.client(
            model=self.model,
            messages=ollama_messages,
            tools=tools,
            stream=True,
            options={'num_predict': max_tokens, 'think': False}
        )
        for chunk in stream:
            yield chunk.message.content

    def invoke(self, messages: list[dict], tools: list[Tool] | None, max_tokens: int) -> AssistantTurn:
        ollama_messages = self._to_ollama_messages(messages)

        if tools:
            tools = self._convert_tools(tools)

        response = self.client(
            model=self.model,
            messages=ollama_messages,
            tools=tools,
            options={'num_predict': max_tokens, 'think': False}
        )
        
        return self._to_assistant_turn(response)  

    def _to_ollama_messages(self, turns: list[Turn]) -> list[dict]:
        messages = []
        for turn in turns:
            if isinstance(turn.content, str):
                messages.append({'role': turn.role, 'content': turn.content})
            else:
                # Handle list[ContentBlock] - extract components
                texts = []
                images = []
                tool_calls = []
                tool_results = []

                for block in turn.content:
                    if isinstance(block, TextContent):
                        texts.append(block.text)
                    elif isinstance(block, ImageContent):
                        # Ollama expects base64 data directly
                        # TODO: fetch URL if source_type == "url"
                        images.append(block.data)
                    elif isinstance(block, ToolUseContent):
                        tool_calls.append({
                            'function': {
                                'name': block.name,
                                'arguments': block.arguments
                            }
                        })
                    elif isinstance(block, ToolResultContent):
                        tool_results.append(block)

                # Build the main message (assistant or user with text/images)
                if texts or images or tool_calls:
                    msg = {'role': turn.role, 'content': '\n'.join(texts)}
                    if images:
                        msg['images'] = images
                    if tool_calls:
                        msg['tool_calls'] = tool_calls
                    messages.append(msg)

                # Tool results become separate "tool" role messages
                for result in tool_results:
                    msg = {
                        'role': 'tool',
                        'content': result.content
                    }
                    # Include tool name if available (helps model match results)
                    if hasattr(result, 'tool_name') and result.tool_name:
                        msg['name'] = result.tool_name
                    messages.append(msg)

        return messages

    def _to_assistant_turn(self, response) -> AssistantTurn:
        content: str | list = response.message.content or ""
        stop_reason = "end_turn" if response.done_reason == "stop" else "max_tokens"

        if response.message.tool_calls:
            stop_reason = "tool_use"
            content_blocks = []

            if response.message.content:
                content_blocks.append(TextContent(text=response.message.content))

            for tool_call in response.message.tool_calls:
                content_blocks.append(ToolUseContent(
                    id=tool_call.function.name,  # Ollama doesn't provide IDs, use name
                    name=tool_call.function.name,
                    arguments=tool_call.function.arguments
                ))

            content = content_blocks

        return AssistantTurn(
            content=content,
            model=response.model,
            stop_reason=stop_reason,
            usage=Usage(
                input_tokens=response.prompt_eval_count,
                output_tokens=response.eval_count
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
