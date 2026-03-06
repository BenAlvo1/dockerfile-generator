import pytest

from dockerfile_gen.agent.nodes.validate_output import validate_output, _looks_like_error


# --- _looks_like_error unit tests ---

def test_clean_output_is_not_error():
    assert _looks_like_error("Hello, World!\n") is False


def test_traceback_is_error():
    assert _looks_like_error("Traceback (most recent call last):\n  File ...") is True


def test_usage_line_is_error():
    assert _looks_like_error("Usage: script.py <input>") is True


def test_node_internal_is_error():
    assert _looks_like_error("node:internal/errors: blah") is True


def test_bash_command_not_found():
    assert _looks_like_error("bash: foo: command not found") is True


def test_empty_output_is_not_error():
    assert _looks_like_error("") is False


# --- validate_output node tests ---

def _state(**kwargs) -> dict:
    defaults = {
        "exit_code": 0,
        "run_output": "Hello World\n",
        "failure_stage": "",
        "success": False,
        "error": None,
    }
    defaults.update(kwargs)
    return defaults


def test_success_on_clean_output():
    result = validate_output(_state())
    assert result["success"] is True
    assert result["error"] is None


def test_fail_on_nonzero_exit():
    result = validate_output(_state(exit_code=1, failure_stage="run"))
    assert result["success"] is False
    assert result["failure_stage"] == "run"


def test_fail_on_error_looking_output():
    result = validate_output(_state(run_output="Traceback (most recent call last):\n  ..."))
    assert result["success"] is False
    assert result["failure_stage"] == "validation"
