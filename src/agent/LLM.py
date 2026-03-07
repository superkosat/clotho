from abc import ABC, abstractmethod
from collections.abc import Iterator

from agent.models.tool import Tool
from agent.models.turn import AssistantTurn, Turn

class LLM(ABC):
    @abstractmethod
    def invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int) -> AssistantTurn:
        """
        Returns a complete model response to a list of turns once inference
        has completed
        
        :param self: Description
        :param messages: Description
        :type messages: list[Turn]
        :param tools: Description
        :type tools: list[Tool] | None
        :param max_tokens: Description
        :type max_tokens: int
        :return: Description
        :rtype: AssistantTurn
        """

    @abstractmethod
    def stream_invoke(self, messages: list[Turn], tools: list[Tool] | None, max_tokens: int) -> Iterator[str]:
        """
        Streams incremental chunks of an LLM response to a list of turns 
        as they are generated
        
        :param self: Description
        :param messages: Description
        :type messages: list[Turn]
        :param tools: Description
        :type tools: list[Tool] | None
        :param max_tokens: Description
        :type max_tokens: int
        :return: Description
        :rtype: Iterator[str]
        """

    @abstractmethod
    def compact(self):
        """
        Compacts the context of the model using summarization.
        
        :param self:
        """
