from collections.abc import Iterator

from agent.LLM import LLM, _split_at_nth_user_turn, _format_context_for_summary
from agent.models.tool import Tool
from agent.models.turn import Turn, AssistantTurn, SystemTurn, UserTurn
from agent.models.stream_delta import StreamDelta
from agent.models.content_block import TextContent, ImageContent, ToolUseContent, ToolResultContent
from agent.models.usage import Usage
import ollama

_COMPACTION_SYSTEM = (
    "You are a conversation summarizer. Produce a dense, factual summary of the "
    "conversation below. Preserve all important context: decisions made, code written "
    "or modified, file paths touched, problems solved, information discovered, and any "
    "ongoing tasks or open questions. Do not include meta-commentary about the "
    "conversation format. Write as a flowing narrative."
)


_STREAM_TIMEOUT = 120  # seconds — surfaces a hang as an error instead of spinning forever


class OllamaModel(LLM):
    def __init__(
        self,
        model: str,
    ):
        self.model = model
        self.client = ollama.Client(timeout=_STREAM_TIMEOUT)

    def stream_invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int | None) -> Iterator[StreamDelta]:
        ollama_messages = self._to_ollama_messages(messages)
        converted_tools = self._convert_tools(tools) if tools else None

        options: dict = {'think': False}
        if max_tokens is not None:
            options['num_predict'] = max_tokens

        stream = self.client.chat(
            model=self.model,
            messages=ollama_messages,
            tools=converted_tools,
            stream=True,
            options=options,
        )

        collected_text = ""
        model_name = self.model
        input_tokens = 0
        output_tokens = 0
        stop_reason = "end_turn"
        tool_use_blocks = []

        for chunk in stream:
            model_name = chunk.model or model_name

            if chunk.message.content:
                collected_text += chunk.message.content
                yield StreamDelta(type="text_delta", text=chunk.message.content)

            if chunk.message.tool_calls:
                stop_reason = "tool_use"
                for tc in chunk.message.tool_calls:
                    tool_id = tc.function.name
                    tool_use_blocks.append(ToolUseContent(
                        id=tool_id,
                        name=tc.function.name,
                        arguments=tc.function.arguments,
                    ))
                    yield StreamDelta(
                        type="tool_use_start",
                        tool_call_id=tool_id,
                        tool_call_name=tc.function.name,
                    )

            if hasattr(chunk, 'prompt_eval_count') and chunk.prompt_eval_count:
                input_tokens = chunk.prompt_eval_count
            if hasattr(chunk, 'eval_count') and chunk.eval_count:
                output_tokens = chunk.eval_count

            if hasattr(chunk, 'done_reason') and chunk.done_reason:
                if chunk.done_reason == "stop":
                    stop_reason = stop_reason if stop_reason == "tool_use" else "end_turn"
                else:
                    stop_reason = "max_tokens"

        content_blocks = []
        if collected_text:
            content_blocks.append(TextContent(text=collected_text))
        content_blocks.extend(tool_use_blocks)

        if len(content_blocks) == 1 and isinstance(content_blocks[0], TextContent):
            content = content_blocks[0].text
        else:
            content = content_blocks if content_blocks else ""

        assistant_turn = AssistantTurn(
            content=content,
            model=model_name,
            stop_reason=stop_reason,
            usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
        )
        yield StreamDelta(type="message_complete", assistant_turn=assistant_turn)

    def invoke(self, messages: list[dict], tools: list[Tool] | None, max_tokens: int | None) -> AssistantTurn:
        ollama_messages = self._to_ollama_messages(messages)

        if tools:
            tools = self._convert_tools(tools)

        options: dict = {'think': False}
        if max_tokens is not None:
            options['num_predict'] = max_tokens

        response = self.client.chat(
            model=self.model,
            messages=ollama_messages,
            tools=tools,
            options=options,
        )

        return self._to_assistant_turn(response)

    def count_tokens(self, messages: list[Turn], tools: list[Tool] | None) -> int:
        """Estimate token count using a character-based heuristic (chars / 4)."""
        import json
        total = sum(len(t.model_dump_json()) for t in messages)
        if tools:
            total += sum(len(json.dumps({
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            })) for t in tools)
        return total // 4

    def compact(
        self,
        context: list[Turn],
        fresh_system_turn: SystemTurn,
        preserve_last_n: int,
        max_summary_tokens: int,
    ) -> list[Turn]:
        to_preserve, to_summarize = _split_at_nth_user_turn(context, preserve_last_n)
        if not to_summarize:
            return context

        formatted = _format_context_for_summary(to_summarize)
        messages = self._to_ollama_messages([
            SystemTurn(content=_COMPACTION_SYSTEM),
            UserTurn(content=f"Please summarize this conversation:\n\n{formatted}"),
        ])

        options: dict = {'think': False, 'num_predict': max_summary_tokens}
        response = self.client.chat(
            model=self.model,
            messages=messages,
            options=options,
        )
        summary = response.message.content or "(no summary produced)"
        summary_turn = UserTurn(content=f"[CONVERSATION SUMMARY]\n{summary}")
        return [fresh_system_turn, summary_turn] + to_preserve

    def _to_ollama_messages(self, turns: list[Turn]) -> list[dict]:
        messages = []
        for turn in turns:
            if isinstance(turn.content, str):
                messages.append({'role': turn.role, 'content': turn.content})
            else:
                texts = []
                images = []
                tool_calls = []
                tool_results = []

                for block in turn.content:
                    if isinstance(block, TextContent):
                        texts.append(block.text)
                    elif isinstance(block, ImageContent):
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

                if texts or images or tool_calls:
                    msg = {'role': turn.role, 'content': '\n'.join(texts)}
                    if images:
                        msg['images'] = images
                    if tool_calls:
                        msg['tool_calls'] = tool_calls
                    messages.append(msg)

                for result in tool_results:
                    msg = {
                        'role': 'tool',
                        'content': result.content
                    }
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
                    id=tool_call.function.name,
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
