from langchain_core.language_models import BaseChatModel
from langchain_anthropic import ChatAnthropic

from dockerfile_gen.llm.base import LLMProvider


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str, api_key: str):
        self._model = model
        self._api_key = api_key

    def create_model(self) -> BaseChatModel:
        return ChatAnthropic(model=self._model, api_key=self._api_key)
