from abc import ABC, abstractmethod
from collections.abc import Iterator

from agent.models.stream_delta import StreamDelta
from agent.models.tool import Tool
from agent.models.turn import AssistantTurn, SystemTurn, Turn, UserTurn
from agent.models.content_block import TextContent, ToolResultContent


_TOOL_RESULT_TRUNCATE = 300  # chars kept from each tool result in summary


def _split_at_nth_user_turn(
    context: list[Turn],
    preserve_last_n: int,
) -> tuple[list[Turn], list[Turn]]:
    """Split non-system turns into (to_preserve, to_summarize).

    Splits at the Nth-from-last UserTurn boundary so we never break inside a
    tool-use cycle.  Returns (turns_to_preserve, turns_to_summarize).
    If there are not enough UserTurns to split, returns (non_system, []).
    """
    non_system = [t for t in context if not isinstance(t, SystemTurn)]
    user_indices = [i for i, t in enumerate(non_system) if isinstance(t, UserTurn)]

    if len(user_indices) <= preserve_last_n:
        return non_system, []

    cut = user_indices[-preserve_last_n]
    return non_system[cut:], non_system[:cut]


def _format_context_for_summary(turns: list[Turn]) -> str:
    """Render turns as readable text for the summarisation prompt.

    Tool results are truncated aggressively to keep the prompt short.
    """
    lines: list[str] = []
    for turn in turns:
        if isinstance(turn, UserTurn):
            if isinstance(turn.content, str):
                text = turn.content
            else:
                text = " ".join(
                    b.text for b in turn.content if isinstance(b, TextContent)
                )
            lines.append(f"User: {text}")

        elif isinstance(turn, AssistantTurn):
            if isinstance(turn.content, str):
                text = turn.content
            else:
                text = " ".join(
                    b.text for b in turn.content if isinstance(b, TextContent)
                )
            if text:
                lines.append(f"Assistant: {text}")

        elif turn.role == "tool":
            if isinstance(turn.content, list):
                for block in turn.content:
                    if isinstance(block, ToolResultContent):
                        raw = block.content or ""
                        truncated = raw[:_TOOL_RESULT_TRUNCATE]
                        if len(raw) > _TOOL_RESULT_TRUNCATE:
                            truncated += f"… [{len(raw) - _TOOL_RESULT_TRUNCATE} chars truncated]"
                        prefix = "ERROR: " if block.is_error else ""
                        lines.append(f"Tool({block.tool_name}): {prefix}{truncated}")
            elif isinstance(turn.content, str):
                lines.append(f"Tool: {turn.content[:_TOOL_RESULT_TRUNCATE]}")

    return "\n\n".join(lines)


class LLM(ABC):
    @abstractmethod
    def invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int | None) -> AssistantTurn:
        """Returns a complete model response once inference has completed."""

    @abstractmethod
    def stream_invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int | None) -> Iterator[StreamDelta]:
        """Streams incremental deltas; final delta is message_complete with full AssistantTurn."""

    @abstractmethod
    def count_tokens(self, messages: list[Turn], tools: list[Tool] | None) -> int:
        """Return the token count for messages+tools as the provider counts them."""

    @abstractmethod
    def compact(
        self,
        context: list[Turn],
        fresh_system_turn: SystemTurn,
        preserve_last_n: int,
        max_summary_tokens: int,
    ) -> list[Turn]:
        """Summarise old turns and return a complete new context.

        Returns [fresh_system_turn] + [UserTurn(summary)] + last_preserved_turns.
        If there are not enough turns to compact, returns the context unchanged.
        """
