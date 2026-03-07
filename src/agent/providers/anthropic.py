from collections.abc import Iterator

import anthropic

from agent.LLM import LLM
from agent.models.tool import Tool
from agent.models.turn import AssistantTurn, SystemTurn, Turn
from agent.models.content_block import ImageContent, TextContent, ToolUseContent, ToolResultContent
from agent.models.usage import Usage


class AnthropicModel(LLM):
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.model = model
        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
        )

    def invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int) -> AssistantTurn:
        system, anthropic_messages = self._to_anthropic_messages(messages)

        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=anthropic_messages,
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = self.client.messages.create(**kwargs)
        return self._to_assistant_turn(response)

    def stream_invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int) -> Iterator[str]:
        system, anthropic_messages = self._to_anthropic_messages(messages)

        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=anthropic_messages,
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        with self.client.messages.stream(**kwargs) as stream:
            for chunk in stream.text_stream:
                yield chunk

    def _to_anthropic_messages(self, turns: list[Turn]) -> tuple[str | None, list[dict]]:
        """Convert universal turns to Anthropic message format.

        Returns (system_prompt, messages) where system_prompt is extracted from
        any SystemTurn (Anthropic requires it as a top-level parameter, not a message).
        """
        system = None
        messages = []

        for turn in turns:
            if isinstance(turn, SystemTurn):
                system = turn.content
                continue

            if turn.role == "tool":
                # Tool results go as a user message with tool_result content blocks
                tool_results = self._convert_tool_results(turn.content)
                messages.append({"role": "user", "content": tool_results})
                continue

            content = self._convert_content(turn.content)
            messages.append({"role": turn.role, "content": content})

        return system, messages

    def _convert_content(self, content: str | list) -> str | list[dict]:
        if isinstance(content, str):
            return content

        blocks = []
        for block in content:
            if isinstance(block, TextContent):
                blocks.append({"type": "text", "text": block.text})
            elif isinstance(block, ImageContent):
                if block.source_type == "base64":
                    blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": block.media_type,
                            "data": block.data,
                        }
                    })
                else:
                    blocks.append({
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": block.data,
                        }
                    })
            elif isinstance(block, ToolUseContent):
                blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.arguments,
                })
            # ToolResultContent in an assistant turn would be unusual; skip
        return blocks

    def _convert_tool_results(self, content: str | list) -> list[dict]:
        """Convert ToolTurn content to Anthropic tool_result blocks."""
        if isinstance(content, str):
            return [{"type": "tool_result", "tool_use_id": "", "content": content}]

        blocks = []
        for block in content:
            if isinstance(block, ToolResultContent):
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": block.tool_use_id,
                    "content": block.content,
                    "is_error": block.is_error,
                })
        return blocks

    def _to_assistant_turn(self, response) -> AssistantTurn:
        stop_reason_map = {
            "end_turn": "end_turn",
            "tool_use": "tool_use",
            "max_tokens": "max_tokens",
            "stop_sequence": "stop_sequence",
            "refusal": "content_filter",
            "pause_turn": "end_turn",
        }
        stop_reason = stop_reason_map.get(response.stop_reason, "end_turn")

        content_blocks = []
        for block in response.content:
            if block.type == "text":
                content_blocks.append(TextContent(text=block.text))
            elif block.type == "tool_use":
                content_blocks.append(ToolUseContent(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))

        content = content_blocks if len(content_blocks) != 1 or not isinstance(content_blocks[0], TextContent) else content_blocks[0].text

        return AssistantTurn(
            content=content,
            model=response.model,
            stop_reason=stop_reason,
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
        )

    def _convert_tools(self, tools: list[Tool]) -> list[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in tools
        ]

    def compact(self):
        pass
