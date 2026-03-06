from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    llm_provider: Literal["openai", "anthropic", "groq"] = Field(default="openai", description="LLM provider: openai, anthropic, or groq")
    llm_model: str = Field(default="gpt-4o-mini", description="Model name for the chosen provider")
    openai_api_key: str = Field(default="", description="OpenAI API key")
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    groq_api_key: str = Field(default="", description="Groq API key")
    max_attempts: int = Field(default=3, description="Max Dockerfile build+run attempts before failing")
    docker_build_timeout: int = Field(default=120, description="Docker build timeout in seconds")
    docker_run_timeout: int = Field(default=30, description="Docker run timeout in seconds")
    langfuse_enabled: bool = Field(default=False, description="Enable Langfuse observability")
    langfuse_public_key: str = Field(default="", description="Langfuse public key")
    langfuse_secret_key: str = Field(default="", description="Langfuse secret key")
    langfuse_host: str = Field(default="http://localhost:3000", description="Langfuse server URL")


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()
