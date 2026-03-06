import pytest

from dockerfile_gen.config import Config


def test_default_provider():
    config = Config(openai_api_key="test", _env_file=None)
    assert config.llm_provider == "openai"


def test_default_model():
    config = Config(openai_api_key="test", _env_file=None)
    assert config.llm_model == "gpt-4o-mini"


def test_default_max_attempts():
    config = Config(openai_api_key="test", _env_file=None)
    assert config.max_attempts == 3


def test_langfuse_disabled_by_default():
    config = Config(openai_api_key="test", _env_file=None)
    assert config.langfuse_enabled is False


def test_override_via_fields():
    config = Config(
        llm_provider="anthropic",
        llm_model="claude-3-5-haiku-20241022",
        max_attempts=5,
        anthropic_api_key="test-key",
        _env_file=None,
    )
    assert config.llm_provider == "anthropic"
    assert config.llm_model == "claude-3-5-haiku-20241022"
    assert config.max_attempts == 5
