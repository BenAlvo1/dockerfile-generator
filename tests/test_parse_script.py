import os
import tempfile

import pytest

from dockerfile_gen.agent.nodes.parse_script import parse_script, LANGUAGE_MAP


def _state(path: str) -> dict:
    return {"script_path": path}


def test_python_language_detection():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("print('hello')\n")
        path = f.name
    try:
        result = parse_script(_state(path))
        assert result["language"] == "python"
    finally:
        os.unlink(path)


def test_javascript_language_detection():
    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
        f.write("console.log('hi');\n")
        path = f.name
    try:
        result = parse_script(_state(path))
        assert result["language"] == "javascript"
    finally:
        os.unlink(path)


def test_unknown_extension_falls_back():
    with tempfile.NamedTemporaryFile(suffix=".xyz", mode="w", delete=False) as f:
        f.write("some content\n")
        path = f.name
    try:
        result = parse_script(_state(path))
        assert result["language"] == "unknown"
    finally:
        os.unlink(path)


def test_image_tag_slug_generation():
    with tempfile.NamedTemporaryFile(suffix=".py", prefix="my_script", mode="w", delete=False) as f:
        f.write("pass\n")
        path = f.name
    try:
        result = parse_script(_state(path))
        assert result["image_tag"].startswith("jit-gen-")
        assert result["image_tag"].endswith(":latest")
        assert "_" not in result["image_tag"]
    finally:
        os.unlink(path)


def test_script_content_is_read():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("x = 42\n")
        path = f.name
    try:
        result = parse_script(_state(path))
        assert result["script_content"] == "x = 42\n"
    finally:
        os.unlink(path)


def test_missing_file_returns_error():
    result = parse_script(_state("/nonexistent/path/script.py"))
    assert "error" in result
    assert result["is_safe"] is False


def test_all_mapped_languages():
    expected = {"python", "javascript", "typescript", "bash", "ruby", "go", "rust", "java"}
    assert set(LANGUAGE_MAP.values()) == expected
