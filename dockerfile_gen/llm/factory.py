from langchain_core.language_models import BaseChatModel

from dockerfile_gen.config import Config
from dockerfile_gen.llm.base import LLMProvider
from dockerfile_gen.llm.openai_provider import OpenAIProvider
from dockerfile_gen.llm.anthropic_provider import AnthropicProvider
from dockerfile_gen.llm.groq_provider import GroqProvider


def create_provider(config: Config) -> LLMProvider:
    match config.llm_provider.lower():
        case "openai":
            return OpenAIProvider(model=config.llm_model, api_key=config.openai_api_key)
        case "anthropic":
            return AnthropicProvider(model=config.llm_model, api_key=config.anthropic_api_key)
        case "groq":
            return GroqProvider(model=config.llm_model, api_key=config.groq_api_key)
        case _:
            raise ValueError(
                f"Unsupported LLM provider: {config.llm_provider!r}. Choose 'openai', 'anthropic', or 'groq'."
            )


def create_model(config: Config) -> BaseChatModel:
    return create_provider(config).create_model()
