from abc import ABC, abstractmethod
from langchain_core.language_models import BaseChatModel


class LLMProvider(ABC):
    @abstractmethod
    def create_model(self) -> BaseChatModel:
        raise NotImplementedError
