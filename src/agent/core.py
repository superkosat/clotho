# Main agent loop, agent logic

import asyncio
import inspect
import os
import queue
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Callable, Awaitable

from agent.models.tool import Tool
from agent.models.content_block import ContentBlock, ImageContent, TextContent, ToolUseContent, ToolResultContent
from agent.models.stream_delta import StreamDelta
from agent.models.turn import AssistantTurn, CompactionTurn, SystemTurn, UserTurn, ToolTurn
from agent.providers.anthropic import AnthropicModel
from agent.providers.openai import OpenAIModel
from agent.utils.projects import *
from agent.tools.functions.bash import set_sandbox_instance
from agent.prompts.system_prompt import build_system_prompt, build_environment_info
from skills.loader import load_skills, build_skills_prompt_section

from dotenv import load_dotenv
from uuid import uuid4, UUID

from exceptions import NoModelConfiguredError, NoActiveChatError, ProviderNotSupportedError
from sandbox.config import create_sandbox_from_config, is_sandbox_enabled
from sandbox.exceptions import SandboxImageNotFoundError

load_dotenv()

_COMPACTION_THRESHOLD = 0.75  # compact when context reaches 75% of window
_COMPACTION_PRESERVE_N = 4    # preserve last N user exchanges
_COMPACTION_TARGET_PCT = 0.30 # aim for summary to be ~30% of context window


class ClothoController():
    def __init__(self):
        self.model = None           # LLM
        self.current_project_id = None
        self.context = None         # list[Turn]
        self.tools = None
        self.sandbox = None
        self.context_window: int | None = None
        self.max_output_tokens: int | None = None
        self._last_input_tokens: int = 0

    async def run(
        self,
        user_input: str,
        emit: Callable[[str, dict], Awaitable[None]],
        request_approval: Callable[[list[dict]], Awaitable[dict[str, str]]],
        stream: bool = False,
        cancel_event: asyncio.Event | None = None,
        content: list[dict] | None = None,
    ):
        def _check_cancelled():
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError("Run cancelled")

        _check_cancelled()

        # Pre-invoke compaction check (before the new user turn is added)
        await self._check_and_compact(emit, cancel_event)

        # Build user turn: use structured content blocks if provided,
        # otherwise fall back to plain text string.
        if content:
            from pydantic import TypeAdapter
            block_adapter = TypeAdapter(ContentBlock)
            blocks = [block_adapter.validate_python(b) for b in content]
            turn = UserTurn(content=blocks)
        else:
            turn = UserTurn(content=user_input)
        _check_cancelled()
        if stream:
            response = await self._stream_and_emit(turn, emit, cancel_event)
        else:
            response = await asyncio.to_thread(self.invoke, turn)
            await self._emit_content(response, emit)

        if response and response.usage:
            self._last_input_tokens = response.usage.input_tokens

        # Tool use loop
        consecutive_denials = 0
        max_consecutive_denials = 3
        while response.stop_reason == "tool_use":
            _check_cancelled()

            tool_uses = [b for b in response.content if isinstance(b, ToolUseContent)]

            tool_call_dicts = [
                {"id": t.id, "name": t.name, "arguments": t.arguments}
                for t in tool_uses
            ]
            verdicts = await request_approval(tool_call_dicts)

            _check_cancelled()

            all_denied = all(verdicts.get(t.id) != "allow" for t in tool_uses)
            tool_results = []
            for tool_use in tool_uses:
                _check_cancelled()

                verdict = verdicts.get(tool_use.id, "user_deny")

                if verdict == "allow":
                    result = await asyncio.to_thread(self._execute_tool, tool_use)
                elif verdict == "policy_deny":
                    result = ToolResultContent(
                        tool_use_id=tool_use.id,
                        tool_name=tool_use.name,
                        content=f"Tool '{tool_use.name}' is not permitted by the current permission policy.",
                        is_error=True,
                    )
                else:
                    result = ToolResultContent(
                        tool_use_id=tool_use.id,
                        tool_name=tool_use.name,
                        content=f"Tool '{tool_use.name}' denied by user. Try a different approach.",
                        is_error=True,
                    )

                tool_results.append(result)
                await emit("agent.tool_result", {
                    "tool_use_id": result.tool_use_id,
                    "tool_name": result.tool_name,
                    "content": result.content,
                    "is_error": result.is_error,
                })

            if all_denied:
                consecutive_denials += 1
                if consecutive_denials >= max_consecutive_denials:
                    break
            else:
                consecutive_denials = 0

            _check_cancelled()

            # Compaction check before re-invoking with tool results
            await self._check_and_compact(emit, cancel_event)

            tool_turn = ToolTurn(content=tool_results)
            if stream:
                response = await self._stream_and_emit(tool_turn, emit, cancel_event)
            else:
                response = await asyncio.to_thread(self.invoke, tool_turn)
                await self._emit_content(response, emit)

            if response and response.usage:
                self._last_input_tokens = response.usage.input_tokens

        await emit("agent.turn_complete", {
            "stop_reason": response.stop_reason,
            "model": response.model,
            "usage": response.usage.model_dump(),
        })

    def _estimate_tokens_heuristic(self) -> int:
        """Rough token estimate: total JSON bytes of context / 4."""
        if not self.context:
            return 0
        return sum(len(t.model_dump_json()) for t in self.context) // 4

    async def _check_and_compact(
        self,
        emit: Callable[[str, dict], Awaitable[None]] | None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        """Check if context is over the threshold and compact if so."""
        if not self.context_window or not self.context or not self.model:
            return

        # Need more than preserve_last_n user turns to have anything to compact
        user_turn_count = sum(1 for t in self.context if isinstance(t, UserTurn))
        if user_turn_count <= _COMPACTION_PRESERVE_N:
            return

        # Count tokens
        try:
            current_tokens = await asyncio.to_thread(
                self.model.count_tokens, self.context, self.tools
            )
            self._last_input_tokens = current_tokens
        except Exception:
            current_tokens = self._last_input_tokens or self._estimate_tokens_heuristic()

        if current_tokens / self.context_window < _COMPACTION_THRESHOLD:
            return

        if cancel_event and cancel_event.is_set():
            return

        if emit:
            await emit("agent.compaction_started", {
                "tokens_before": current_tokens,
                "context_window": self.context_window,
            })

        await self._run_compaction_inner(current_tokens, emit)

    async def compact_context(
        self,
        emit: Callable[[str, dict], Awaitable[None]] | None = None,
    ) -> dict:
        """Manually compact the context. Returns compaction metadata.

        Raises ValueError if session is not ready or context is too small.
        """
        if not self.context or not self.model:
            raise ValueError("No active session to compact")

        user_turn_count = sum(1 for t in self.context if isinstance(t, UserTurn))
        if user_turn_count <= _COMPACTION_PRESERVE_N:
            raise ValueError(
                f"Not enough conversation history to compact — need more than "
                f"{_COMPACTION_PRESERVE_N} exchanges."
            )

        try:
            current_tokens = await asyncio.to_thread(
                self.model.count_tokens, self.context, self.tools
            )
            self._last_input_tokens = current_tokens
        except Exception:
            current_tokens = self._last_input_tokens or self._estimate_tokens_heuristic()

        return await self._run_compaction_inner(current_tokens, emit)

    async def _run_compaction_inner(
        self,
        tokens_before: int,
        emit: Callable[[str, dict], Awaitable[None]] | None,
    ) -> dict:
        """Execute compaction and persist. Returns metadata dict."""
        env_info = build_environment_info(working_directory=os.getcwd())
        skills = load_skills()
        skills_section = build_skills_prompt_section(skills) if skills else None
        prompt = build_system_prompt(environment_info=env_info, skills_section=skills_section)
        fresh_system_turn = SystemTurn(content=prompt)

        max_summary_tokens = min(
            int((self.context_window or 8192) * _COMPACTION_TARGET_PCT),
            self.max_output_tokens or 8192,
        )
        max_summary_tokens = max(max_summary_tokens, 512)  # floor

        new_context = await asyncio.to_thread(
            self.model.compact,
            self.context,
            fresh_system_turn,
            _COMPACTION_PRESERVE_N,
            max_summary_tokens,
        )

        # Strip image blocks from preserved turns — images are ephemeral and
        # their semantic content is captured in the compaction summary. Keeping
        # raw image data causes errors when providers try to re-process stale
        # image references in the restructured context.
        for turn in new_context:
            if isinstance(turn.content, list):
                stripped = [b for b in turn.content if not isinstance(b, ImageContent)]
                if len(stripped) != len(turn.content):
                    if stripped:
                        turn.content = stripped
                    else:
                        turn.content = "(image previously shared)"

        turns_removed = len(self.context) - len(new_context)

        try:
            tokens_after = await asyncio.to_thread(
                self.model.count_tokens, new_context, self.tools
            )
        except Exception:
            tokens_after = None

        self.context = new_context
        self._last_input_tokens = tokens_after or 0

        compaction_turn = CompactionTurn(
            timestamp=datetime.now(timezone.utc).isoformat(),
            turns_removed=turns_removed,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
        )
        append_compaction_record(self.current_project_id, compaction_turn, new_context)

        metadata = {
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "turns_removed": turns_removed,
        }

        if emit:
            await emit("agent.context_compacted", metadata)

        return metadata

    def _execute_tool(self, call: ToolUseContent) -> ToolResultContent:
        tool = next((t for t in self.tools if t.name == call.name), None)
        if not tool:
            return ToolResultContent(
                tool_use_id=call.id, tool_name=call.name,
                content=f"Unknown tool: {call.name}", is_error=True,
            )

        valid_params = inspect.signature(tool.func).parameters
        has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in valid_params.values()
        )
        if has_var_keyword:
            filtered_args = call.arguments
        else:
            filtered_args = {k: v for k, v in call.arguments.items() if k in valid_params}

        try:
            result = tool.func(**filtered_args)
            return ToolResultContent(
                tool_use_id=call.id, tool_name=call.name, content=str(result),
            )
        except Exception as e:
            return ToolResultContent(
                tool_use_id=call.id, tool_name=call.name,
                content=str(e), is_error=True,
            )

    async def _emit_content(
        self,
        response: AssistantTurn,
        emit: Callable[[str, dict], Awaitable[None]],
    ):
        if isinstance(response.content, str):
            if response.content:
                await emit("agent.text", {"text": response.content})
        else:
            for block in response.content:
                if isinstance(block, TextContent):
                    await emit("agent.text", {"text": block.text})

    def set_model(
        self,
        provider: str,
        model: str,
        base_url: str = None,
        api_key: str = None,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
    ):
        match provider:
            case "ollama":
                from agent.providers.ollama import OllamaModel
                self.model = OllamaModel(model=model)
            case "openai":
                self.model = OpenAIModel(model=model, base_url=base_url, api_key=api_key)
            case "anthropic":
                self.model = AnthropicModel(model=model, api_key=api_key, base_url=base_url)
            case _:
                raise ProviderNotSupportedError(provider)

        self.context_window = context_window
        self.max_output_tokens = max_output_tokens

    def new_chat(self) -> bool:
        self.current_project_id = uuid4()

        env_info = build_environment_info(working_directory=os.getcwd())
        skills = load_skills()
        skills_section = build_skills_prompt_section(skills) if skills else None

        _builtin = {"bash", "read", "write", "edit"}
        extra_tools = [t for t in (self.tools or []) if t.name not in _builtin]
        extra_tools_section = (
            "\n".join(f"- `{t.name}`: {t.description}" for t in extra_tools)
            if extra_tools else None
        )

        prompt = build_system_prompt(
            environment_info=env_info,
            skills_section=skills_section,
            tools_section=extra_tools_section,
        )
        system_turn = SystemTurn(content=prompt)

        if (create_project_file(self.current_project_id, system_turn=system_turn)):
            self.context = [system_turn]
            self._init_sandbox()
            return True
        else:
            return False

    def load_chat(self, id: UUID) -> bool:
        history_from_file = read_content_from_project_file(id)

        if history_from_file is not None:
            self.context = history_from_file
            self.current_project_id = id
            self._init_sandbox()
            return True
        else:
            return False

    def delete_chat(self) -> bool:
        self._cleanup_sandbox()
        if (delete_project_file(self.current_project_id)):
            self.current_project_id = None
            self.context = None
            self.new_chat()
            return True
        else:
            return False

    def checkpoint_turn(self, input_turn: UserTurn | ToolTurn, assistant_turn: AssistantTurn) -> bool:
        if (append_to_project_file(
            self.current_project_id,
            input_turn=input_turn,
            assistant_turn=assistant_turn
        )):
            return True
        else:
            return False

    def invoke(self, turn: UserTurn | ToolTurn) -> AssistantTurn:
        if self.model is None:
            raise NoModelConfiguredError()
        if self.context is None:
            raise NoActiveChatError()

        self.context.append(turn)
        response = self.model.invoke(self.context, tools=self.tools, max_tokens=self.max_output_tokens)
        self.context.append(response)
        self.checkpoint_turn(input_turn=turn, assistant_turn=response)
        return response

    def stream_invoke(self, turn: UserTurn | ToolTurn) -> Iterator[StreamDelta]:
        if self.model is None:
            raise NoModelConfiguredError()
        if self.context is None:
            raise NoActiveChatError()

        self.context.append(turn)
        assistant_turn = None
        for delta in self.model.stream_invoke(self.context, tools=self.tools, max_tokens=self.max_output_tokens):
            if delta.type == "message_complete":
                assistant_turn = delta.assistant_turn
            yield delta

        if assistant_turn:
            self.context.append(assistant_turn)
            self.checkpoint_turn(input_turn=turn, assistant_turn=assistant_turn)

    async def _stream_and_emit(
        self,
        turn: UserTurn | ToolTurn,
        emit: Callable[[str, dict], Awaitable[None]],
        cancel_event: asyncio.Event | None = None,
    ) -> AssistantTurn:
        q: queue.Queue[StreamDelta | BaseException | None] = queue.Queue()

        def _produce():
            try:
                for delta in self.stream_invoke(turn):
                    if cancel_event and cancel_event.is_set():
                        break
                    q.put(delta)
            except BaseException as exc:
                q.put(exc)
                return
            q.put(None)

        thread = asyncio.get_event_loop().run_in_executor(None, _produce)

        assistant_turn = None
        while True:
            if cancel_event and cancel_event.is_set():
                raise asyncio.CancelledError("Stream cancelled")
            try:
                delta = await asyncio.to_thread(q.get, timeout=0.1)
            except queue.Empty:
                continue
            if delta is None:
                break
            if isinstance(delta, BaseException):
                raise delta
            if delta.type == "text_delta":
                await emit("agent.text_delta", {"text": delta.text})
            elif delta.type == "tool_use_start":
                await emit("agent.tool_use_start", {
                    "tool_call_id": delta.tool_call_id,
                    "tool_call_name": delta.tool_call_name,
                })
            elif delta.type == "tool_use_delta":
                await emit("agent.tool_use_delta", {
                    "text": delta.text,
                    "tool_call_id": delta.tool_call_id,
                })
            elif delta.type == "message_complete":
                assistant_turn = delta.assistant_turn

        await thread
        return assistant_turn

    def register_tools(self, tools: list[Tool]):
        self.tools = tools

    def deregister_tools(self):
        self.tools = None

    def _init_sandbox(self):
        if not is_sandbox_enabled():
            return
        try:
            self.sandbox = create_sandbox_from_config(
                session_id=str(self.current_project_id),
                workspace_path=os.getcwd(),
            )
            self.sandbox.start()
            set_sandbox_instance(self.sandbox)
        except SandboxImageNotFoundError:
            print("Sandbox image not found. Building clotho-sandbox:latest...")
            from sandbox.build_image import build_sandbox_image
            if build_sandbox_image():
                try:
                    self.sandbox.start()
                    set_sandbox_instance(self.sandbox)
                except Exception as e:
                    print(f"Warning: Failed to start sandbox after build: {e}")
                    self.sandbox = None
                    set_sandbox_instance(None)
            else:
                print("Warning: Sandbox image build failed. Sandbox unavailable.")
                self.sandbox = None
                set_sandbox_instance(None)
        except Exception as e:
            print(f"Warning: Failed to initialize sandbox: {e}")
            self.sandbox = None
            set_sandbox_instance(None)

    def _cleanup_sandbox(self):
        if self.sandbox:
            try:
                self.sandbox.cleanup()
            except Exception as e:
                try:
                    import sys
                    if sys is not None and sys.meta_path is not None:
                        print(f"Warning: Error cleaning up sandbox: {e}")
                except:
                    pass
            finally:
                self.sandbox = None
                set_sandbox_instance(None)

    def __del__(self):
        try:
            import sys
            if sys is None or sys.meta_path is None:
                return
        except (ImportError, AttributeError):
            return
        self._cleanup_sandbox()
