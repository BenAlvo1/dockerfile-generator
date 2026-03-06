import json
from unittest.mock import MagicMock, patch

from dockerfile_gen.agent.nodes.reflect_and_fix import make_reflect_node, FixedSpec


def _make_state(**overrides) -> dict:
    base = {
        "script_filename": "app.py",
        "script_content": "print('hello')",
        "base_image": "python:3.99-slim",  # fictitious broken tag
        "dockerfile": (
            "FROM python:3.99-slim\n"
            "COPY app.py .\n"
            'ENTRYPOINT ["python", "app.py"]'
        ),
        "test_args": "",
        "failure_stage": "build",
        "build_output": "ERROR: manifest for python:3.99-slim not found: not found",
        "run_output": "",
        "error": "Docker build failed: image not found",
    }
    base.update(overrides)
    return base


def _mock_urlopen(tags: list[str]):
    payload = json.dumps({"results": [{"name": t} for t in tags]}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = payload
    return mock_resp


def _make_llm(tool_call_args: dict | None, fixed: FixedSpec) -> MagicMock:
    """Mock LLM that optionally issues one tool call, then returns a FixedSpec."""
    mock_llm = MagicMock()

    tool_response = MagicMock()
    tool_response.tool_calls = (
        [{"id": "tc_001", "name": "find_compatible_image", "args": tool_call_args}]
        if tool_call_args else []
    )
    mock_llm.bind_tools.return_value.invoke.return_value = tool_response
    mock_llm.with_structured_output.return_value.invoke.return_value = fixed

    return mock_llm


# ---------------------------------------------------------------------------
# Tool call path
# ---------------------------------------------------------------------------

class TestReflectWithToolCall:
    def test_updates_base_image_from_new_from_line(self):
        fixed = FixedSpec(
            dockerfile=(
                "FROM python:3.12-slim\n"
                "COPY app.py .\n"
                'ENTRYPOINT ["python", "app.py"]'
            ),
            test_args="",
            analysis="Switched to python:3.12-slim — original tag does not exist.",
        )
        mock_llm = _make_llm(tool_call_args={"repo": "python"}, fixed=fixed)

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(["3.12-slim", "3.11-slim"])):
            node = make_reflect_node(mock_llm)
            result = node(_make_state())

        assert result["base_image"] == "python:3.12-slim"
        assert result["dockerfile"] == fixed.dockerfile

    def test_docker_hub_tags_passed_to_structured_llm(self):
        """Tags returned by the tool must appear in the messages given to the structured LLM."""
        fixed = FixedSpec(
            dockerfile='FROM python:3.11-slim\nCOPY app.py .\nENTRYPOINT ["python", "app.py"]',
            test_args="",
            analysis="Used python:3.11-slim",
        )
        mock_llm = _make_llm(tool_call_args={"repo": "python"}, fixed=fixed)
        hub_tags = ["3.12-slim", "3.11-slim", "3.10-slim"]

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(hub_tags)):
            node = make_reflect_node(mock_llm)
            node(_make_state())

        messages = mock_llm.with_structured_output.return_value.invoke.call_args[0][0]
        tool_msg = next(m for m in messages if isinstance(m, dict) and m.get("role") == "tool")
        for tag in hub_tags:
            assert tag in tool_msg["content"]

    def test_tool_call_id_matches_tool_response(self):
        """The tool result message must reference the same call ID the LLM produced."""
        fixed = FixedSpec(
            dockerfile='FROM python:3.12-slim\nCOPY app.py .\nENTRYPOINT ["python", "app.py"]',
            test_args="",
            analysis="Fixed image.",
        )
        mock_llm = _make_llm(tool_call_args={"repo": "python"}, fixed=fixed)

        with patch("urllib.request.urlopen", return_value=_mock_urlopen(["3.12-slim"])):
            node = make_reflect_node(mock_llm)
            node(_make_state())

        messages = mock_llm.with_structured_output.return_value.invoke.call_args[0][0]
        tool_msg = next(m for m in messages if isinstance(m, dict) and m.get("role") == "tool")
        assert tool_msg["tool_call_id"] == "tc_001"


# ---------------------------------------------------------------------------
# No-tool-call path
# ---------------------------------------------------------------------------

class TestReflectWithoutToolCall:
    def test_docker_hub_not_called_for_non_image_failures(self):
        fixed = FixedSpec(
            dockerfile=(
                "FROM python:3.12-slim\n"
                "RUN pip install requests\n"
                "COPY app.py .\n"
                'ENTRYPOINT ["python", "app.py"]'
            ),
            test_args="",
            analysis="Added missing pip install for requests.",
        )
        mock_llm = _make_llm(tool_call_args=None, fixed=fixed)

        with patch("urllib.request.urlopen") as mock_open:
            node = make_reflect_node(mock_llm)
            result = node(_make_state(
                failure_stage="build",
                build_output="No module named 'requests'",
            ))

        mock_open.assert_not_called()
        assert result["dockerfile"] == fixed.dockerfile

    def test_base_image_not_overwritten_when_from_line_unchanged(self):
        fixed = FixedSpec(
            dockerfile=(
                "FROM python:3.99-slim\n"  # same broken image, LLM didn't change it
                "RUN pip install requests\n"
                "COPY app.py .\n"
                'ENTRYPOINT ["python", "app.py"]'
            ),
            test_args="",
            analysis="Added pip install; did not change image.",
        )
        mock_llm = _make_llm(tool_call_args=None, fixed=fixed)
        node = make_reflect_node(mock_llm)
        result = node(_make_state())

        # base_image must not appear in the update dict when unchanged
        assert "base_image" not in result

    def test_returns_updated_dockerfile_and_test_args(self):
        fixed = FixedSpec(
            dockerfile='FROM python:3.12-slim\nCOPY app.py .\nENTRYPOINT ["python", "app.py"]',
            test_args="--verbose",
            analysis="Fixed entrypoint args.",
        )
        mock_llm = _make_llm(tool_call_args=None, fixed=fixed)
        node = make_reflect_node(mock_llm)
        result = node(_make_state())

        assert result["dockerfile"] == fixed.dockerfile
        assert result["test_args"] == "--verbose"
