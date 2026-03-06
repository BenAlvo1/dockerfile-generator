from unittest.mock import MagicMock

from dockerfile_gen.agent.nodes.fetch_base_image import make_fetch_base_image_node, BASE_IMAGE_MAP, BaseImageSpec


def _make_node(llm=None):
    return make_fetch_base_image_node(llm or MagicMock())


def _state(**kwargs) -> dict:
    return {"language": "unknown", "script_filename": "script.py", "script_content": "", **kwargs}


def test_python_image():
    assert _make_node()(_state(language="python"))["base_image"] == "python:3.12-slim"


def test_javascript_image():
    assert _make_node()(_state(language="javascript"))["base_image"] == "node:20-slim"


def test_typescript_image():
    assert _make_node()(_state(language="typescript"))["base_image"] == "node:20-slim"


def test_bash_image():
    assert _make_node()(_state(language="bash"))["base_image"] == "alpine:3.19"


def test_all_known_languages_use_static_map_without_llm_call():
    mock_llm = MagicMock()
    node = make_fetch_base_image_node(mock_llm)
    for lang in BASE_IMAGE_MAP:
        node(_state(language=lang))
    mock_llm.with_structured_output.return_value.invoke.assert_not_called()


def test_unknown_language_calls_llm():
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = BaseImageSpec(
        base_image="ubuntu:22.04", reasoning="fallback"
    )
    node = make_fetch_base_image_node(mock_llm)
    result = node(_state(language="unknown", script_content="some unknown script"))

    mock_llm.with_structured_output.return_value.invoke.assert_called_once()
    assert result["base_image"] == "ubuntu:22.04"


def test_unknown_language_returns_llm_chosen_image():
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = BaseImageSpec(
        base_image="elixir:1.16-slim", reasoning="detected Elixir syntax"
    )
    node = make_fetch_base_image_node(mock_llm)
    result = node(_state(language="unknown", script_filename="app.exs", script_content="IO.puts 'hello'"))
    assert result["base_image"] == "elixir:1.16-slim"
