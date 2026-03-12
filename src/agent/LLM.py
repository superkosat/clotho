from abc import ABC, abstractmethod
from collections.abc import Iterator

from agent.models.stream_delta import StreamDelta
from agent.models.tool import Tool
from agent.models.turn import AssistantTurn, Turn

class LLM(ABC):
    @abstractmethod
    def invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int) -> AssistantTurn:
        """
        Returns a complete model response to a list of turns once inference
        has completed.
        """

    @abstractmethod
    def stream_invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int) -> Iterator[StreamDelta]:
        """
        Streams incremental deltas of an LLM response. Yields StreamDelta
        objects for text chunks, tool call events, and a final
        message_complete delta containing the full AssistantTurn.
        """

    @abstractmethod
    def compact(self):
        """
        Compacts the context of the model using summarization.
        """
