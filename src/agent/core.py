# Main agent loop, agent logic

import asyncio
import inspect
import os
import queue
from collections.abc import Iterator
from typing import Callable, Awaitable

from agent.models.tool import Tool
from agent.models.content_block import TextContent, ToolUseContent, ToolResultContent
from agent.models.stream_delta import StreamDelta
from agent.models.turn import AssistantTurn, SystemTurn, UserTurn, ToolTurn
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

class ClothoController():
    def __init__(self):
        self.model = None #LLM
        self.current_project_id = None #conversation id
        self.context = None #conversation context
        self.tools = None #available tools
        self.sandbox = None #session-scoped sandbox

    async def run(
        self,
        user_input: str,
        emit: Callable[[str, dict], Awaitable[None]],
        request_approval: Callable[[list[dict]], Awaitable[dict[str, str]]],
        stream: bool = False,
    ):
        """
        Full agent loop. Invokes model, handles tool use cycles, and
        communicates with the client via emit/request_approval callbacks.

        emit(event_type, data) — deliver events to client
        request_approval(tool_calls) — evaluate per-tool permissions, returns
            dict mapping tool call IDs to "allow" or "deny"
        stream — when True, emit incremental text_delta events as tokens arrive
        """
        turn = UserTurn(content=user_input)

        if stream:
            response = await self._stream_and_emit(turn, emit)
        else:
            response = await asyncio.to_thread(self.invoke, turn)
            await self._emit_content(response, emit)

        # Tool use loop
        consecutive_denials = 0
        max_consecutive_denials = 3
        while response.stop_reason == "tool_use":
            tool_uses = [b for b in response.content if isinstance(b, ToolUseContent)]

            tool_call_dicts = [
                {"id": t.id, "name": t.name, "arguments": t.arguments}
                for t in tool_uses
            ]
            verdicts = await request_approval(tool_call_dicts)

            # Process each tool individually based on its verdict
            all_denied = all(verdicts.get(t.id) != "allow" for t in tool_uses)
            tool_results = []
            for tool_use in tool_uses:
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
                else:  # user_deny
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

            # Track consecutive all-denied rounds to prevent infinite loops
            if all_denied:
                consecutive_denials += 1
                if consecutive_denials >= max_consecutive_denials:
                    break
            else:
                consecutive_denials = 0

            # Re-invoke with tool results (including denials, so the model can adapt)
            tool_turn = ToolTurn(content=tool_results)
            if stream:
                response = await self._stream_and_emit(tool_turn, emit)
            else:
                response = await asyncio.to_thread(self.invoke, tool_turn)
                await self._emit_content(response, emit)

        # Signal turn complete
        await emit("agent.turn_complete", {
            "stop_reason": response.stop_reason,
            "model": response.model,
            "usage": response.usage.model_dump(),
        })

    def _execute_tool(self, call: ToolUseContent) -> ToolResultContent:
        """Execute a single tool call. Returns the result."""
        tool = next((t for t in self.tools if t.name == call.name), None)
        if not tool:
            return ToolResultContent(
                tool_use_id=call.id, tool_name=call.name,
                content=f"Unknown tool: {call.name}", is_error=True,
            )

        valid_params = inspect.signature(tool.func).parameters
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
        """Extract text from a response and emit as agent.text events."""
        if isinstance(response.content, str):
            if response.content:
                await emit("agent.text", {"text": response.content})
        else:
            for block in response.content:
                if isinstance(block, TextContent):
                    await emit("agent.text", {"text": block.text})

    def set_model(self, provider: str, model: str, base_url: str = None, api_key: str = None):
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

    def new_chat(self) -> bool:
        """
        Creates a new project file, resets context with system prompt, and
        creates new project file
        """
        self.current_project_id = uuid4()

        env_info = build_environment_info(working_directory=os.getcwd())
        skills = load_skills()
        skills_section = build_skills_prompt_section(skills) if skills else None
        prompt = build_system_prompt(environment_info=env_info, skills_section=skills_section)
        system_turn = SystemTurn(content=prompt)

        if (create_project_file(self.current_project_id, system_turn=system_turn)):
            self.context = [system_turn]
            self._init_sandbox()  # Initialize sandbox if enabled
            return True
        else:
            return False

    def load_chat(self, id: UUID) -> bool:
        """
        Retrieves chat history from project file, sets current project id and
        context
        """
        history_from_file = read_content_from_project_file(id)

        if history_from_file is not None:
            self.context = history_from_file
            self.current_project_id = id
            self._init_sandbox()  # Initialize sandbox if enabled
            return True
        else:
            return False

    def delete_chat(self) -> bool:
        """
        Deletes the current chat's file, sets current project id and context
        to None. Then calls new_chat().
        """
        self._cleanup_sandbox()  # Cleanup sandbox before deleting
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
        """
        Appends a turn to the context, invokes the model with the context,
        and updates the context and project file with both the input turn and
        AssistantTurn, and the context with just the AssistantTurn
        """
        if self.model is None:
            raise NoModelConfiguredError()
        if self.context is None:
            raise NoActiveChatError()

        self.context.append(turn)
        response = self.model.invoke(self.context, tools=self.tools, max_tokens=4000)
        self.context.append(response)
        self.checkpoint_turn(input_turn=turn, assistant_turn=response)
        return response

    def stream_invoke(self, turn: UserTurn | ToolTurn) -> Iterator[StreamDelta]:
        """
        Appends a turn to the context, streams the model response as
        StreamDelta objects. The final delta (message_complete) contains the
        full AssistantTurn which is appended to context and checkpointed.
        """
        if self.model is None:
            raise NoModelConfiguredError()
        if self.context is None:
            raise NoActiveChatError()

        self.context.append(turn)
        assistant_turn = None
        for delta in self.model.stream_invoke(self.context, tools=self.tools, max_tokens=4000):
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
    ) -> AssistantTurn:
        """
        Run stream_invoke in a thread, forwarding deltas to the client via
        emit as they arrive. Returns the final AssistantTurn.
        """
        q: queue.Queue[StreamDelta | None] = queue.Queue()

        def _produce():
            for delta in self.stream_invoke(turn):
                q.put(delta)
            q.put(None)  # sentinel

        thread = asyncio.get_event_loop().run_in_executor(None, _produce)

        assistant_turn = None
        while True:
            delta = await asyncio.to_thread(q.get)
            if delta is None:
                break
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

        await thread  # ensure producer finished
        return assistant_turn
    
    def register_tools(self, tools: list[Tool]):
        self.tools = tools

    def deregister_tools(self):
        self.tools = None

    def _init_sandbox(self):
        """Initialize sandbox for this session if enabled."""
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
        """Cleanup sandbox resources."""
        if self.sandbox:
            try:
                self.sandbox.cleanup()
            except Exception as e:
                # Only print if not in shutdown (avoid "sys.meta_path is None" errors)
                try:
                    import sys
                    if sys is not None and sys.meta_path is not None:
                        print(f"Warning: Error cleaning up sandbox: {e}")
                except:
                    pass  # Suppress all errors during shutdown
            finally:
                self.sandbox = None
                set_sandbox_instance(None)  # Clear global

    def __del__(self):
        """Ensure sandbox is cleaned up on destruction."""
        # During interpreter shutdown, many modules are already torn down
        # (sys.meta_path becomes None). Suppress all cleanup errors in this case.
        try:
            import sys
            if sys is None or sys.meta_path is None:
                # Python is shutting down, skip cleanup (OS will reclaim resources)
                return
        except (ImportError, AttributeError):
            # Cannot determine shutdown state, skip cleanup to be safe
            return

        self._cleanup_sandbox()
