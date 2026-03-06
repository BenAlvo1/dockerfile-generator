from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq

from dockerfile_gen.llm.base import LLMProvider


class GroqProvider(LLMProvider):
    def __init__(self, model: str, api_key: str):
        self._model = model
        self._api_key = api_key

    def create_model(self) -> BaseChatModel:
        return ChatGroq(model=self._model, api_key=self._api_key)
