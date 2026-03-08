from unittest.mock import MagicMock

from dockerfile_gen.agent.nodes.identify_technologies import (
    make_identify_technologies_node,
    TechnologySpec,
)


def _make_node(llm=None):
    return make_identify_technologies_node(llm or MagicMock())


def _state(**kwargs) -> dict:
    return {
        "language": "python",
        "script_filename": "script.py",
        "script_content": "",
        **kwargs,
    }


def _mock_llm(spec: TechnologySpec) -> MagicMock:
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = spec
    return mock_llm


def test_returns_base_image():
    spec = TechnologySpec(
        base_image="python:3.12-slim",
        system_packages=[],
        runtime_packages=["requests"],
        reasoning="Python script with requests import",
    )
    result = _make_node(_mock_llm(spec))(_state())
    assert result["base_image"] == "python:3.12-slim"


def test_returns_system_packages():
    spec = TechnologySpec(
        base_image="alpine:3.19",
        system_packages=["bash", "curl"],
        runtime_packages=[],
        reasoning="Bash script needing curl",
    )
    result = _make_node(_mock_llm(spec))(_state(language="bash", script_filename="run.sh"))
    assert result["system_packages"] == ["bash", "curl"]


def test_returns_runtime_packages():
    spec = TechnologySpec(
        base_image="python:3.12-slim",
        system_packages=[],
        runtime_packages=["numpy", "pandas"],
        reasoning="Data science script",
    )
    result = _make_node(_mock_llm(spec))(_state(script_content="import numpy, pandas"))
    assert result["runtime_packages"] == ["numpy", "pandas"]


def test_always_calls_llm():
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = TechnologySpec(
        base_image="node:20-slim",
        system_packages=[],
        runtime_packages=["axios"],
        reasoning="Node.js script",
    )
    node = make_identify_technologies_node(mock_llm)
    node(_state(language="javascript", script_filename="app.js"))
    mock_llm.with_structured_output.return_value.invoke.assert_called_once()


def test_empty_packages_when_none_needed():
    spec = TechnologySpec(
        base_image="python:3.12-slim",
        system_packages=[],
        runtime_packages=[],
        reasoning="Simple stdlib-only script",
    )
    result = _make_node(_mock_llm(spec))(_state(script_content="print('hello')"))
    assert result["system_packages"] == []
    assert result["runtime_packages"] == []
