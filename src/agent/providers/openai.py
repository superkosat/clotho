import json
from collections.abc import Iterator

from agent.LLM import LLM, _split_at_nth_user_turn, _format_context_for_summary
from agent.models.stream_delta import StreamDelta
from agent.models.tool import Tool
from agent.models.turn import AssistantTurn, SystemTurn, Turn, UserTurn
from agent.models.content_block import ImageContent, TextContent, ToolUseContent, ToolResultContent
from agent.models.usage import Usage
import openai

_COMPACTION_SYSTEM = (
    "You are a conversation summarizer. Produce a dense, factual summary of the "
    "conversation below. Preserve all important context: decisions made, code written "
    "or modified, file paths touched, problems solved, information discovered, and any "
    "ongoing tasks or open questions. Do not include meta-commentary about the "
    "conversation format. Write as a flowing narrative."
)


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

    def stream_invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int | None) -> Iterator[StreamDelta]:
        openai_messages = self._to_openai_messages(messages)

        kwargs = dict(
            model=self.model,
            messages=openai_messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        collected_text = ""
        tool_calls_acc: dict[int, dict] = {}
        model_name = self.model
        stop_reason = "end_turn"
        input_tokens = 0
        output_tokens = 0

        stream = self.client.chat.completions.create(**kwargs)

        for chunk in stream:
            if chunk.model:
                model_name = chunk.model

            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens

            if not chunk.choices:
                continue

            choice = chunk.choices[0]

            if choice.finish_reason:
                if choice.finish_reason == "tool_calls":
                    stop_reason = "tool_use"
                elif choice.finish_reason == "length":
                    stop_reason = "max_tokens"
                else:
                    stop_reason = "end_turn"

            delta = choice.delta
            if not delta:
                continue

            if delta.content:
                collected_text += delta.content
                yield StreamDelta(type="text_delta", text=delta.content)

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc_delta.id or "",
                            "name": tc_delta.function.name if tc_delta.function and tc_delta.function.name else "",
                            "arguments_json": "",
                        }
                        if tc_delta.id and tc_delta.function and tc_delta.function.name:
                            yield StreamDelta(
                                type="tool_use_start",
                                tool_call_id=tc_delta.id,
                                tool_call_name=tc_delta.function.name,
                            )
                    if tc_delta.function and tc_delta.function.arguments:
                        tool_calls_acc[idx]["arguments_json"] += tc_delta.function.arguments
                        yield StreamDelta(
                            type="tool_use_delta",
                            text=tc_delta.function.arguments,
                            tool_call_id=tool_calls_acc[idx]["id"],
                        )

        content_blocks = []
        if collected_text:
            content_blocks.append(TextContent(text=collected_text))
        for idx in sorted(tool_calls_acc.keys()):
            tc = tool_calls_acc[idx]
            stop_reason = "tool_use"
            content_blocks.append(ToolUseContent(
                id=tc["id"],
                name=tc["name"],
                arguments=json.loads(tc["arguments_json"]) if tc["arguments_json"] else {},
            ))

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

    def invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int | None) -> AssistantTurn:
        openai_messages = self._to_openai_messages(messages)

        kwargs = dict(
            model=self.model,
            messages=openai_messages,
        )
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = self.client.chat.completions.create(**kwargs)
        return self._to_assistant_turn(response)

    def count_tokens(self, messages: list[Turn], tools: list[Tool] | None) -> int:
        """Estimate token count using tiktoken."""
        try:
            import tiktoken
            try:
                enc = tiktoken.encoding_for_model(self.model)
            except KeyError:
                enc = tiktoken.get_encoding("cl100k_base")

            total = 0
            openai_messages = self._to_openai_messages(messages)
            for msg in openai_messages:
                total += 4  # per-message overhead
                content = msg.get("content")
                if isinstance(content, str):
                    total += len(enc.encode(content))
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and "text" in part:
                            total += len(enc.encode(part["text"]))
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        total += len(enc.encode(json.dumps(tc)))
            total += 2  # reply priming
            if tools:
                for tool in self._convert_tools(tools):
                    total += len(enc.encode(json.dumps(tool)))
            return total
        except ImportError:
            # tiktoken not available — use heuristic
            return sum(len(t.model_dump_json()) for t in messages) // 4

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
        messages = self._to_openai_messages([
            SystemTurn(content=_COMPACTION_SYSTEM),
            UserTurn(content=f"Please summarize this conversation:\n\n{formatted}"),
        ])

        kwargs: dict = dict(
            model=self.model,
            messages=messages,
            max_tokens=max_summary_tokens,
        )
        response = self.client.chat.completions.create(**kwargs)
        summary = response.choices[0].message.content or "(no summary produced)"
        summary_turn = UserTurn(content=f"[CONVERSATION SUMMARY]\n{summary}")
        return [fresh_system_turn, summary_turn] + to_preserve

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
