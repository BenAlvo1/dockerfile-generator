"""
Fixtures for integration tests.

Safety-blocking tests run without LLM calls (deterministic regex catches threats
before the LLM layer is invoked).  Full end-to-end tests are gated behind the
``e2e`` marker and are skipped automatically when no API key is present.
"""
import os
import subprocess
import sys

import pytest


def _find_project_root() -> str:
    """Walk up from this file until pyproject.toml is found."""
    current = os.path.dirname(os.path.abspath(__file__))
    while current != os.path.dirname(current):  # stop at filesystem root
        if os.path.isfile(os.path.join(current, "pyproject.toml")):
            return current
        current = os.path.dirname(current)
    raise RuntimeError("Could not find project root (pyproject.toml not found)")


PROJECT_ROOT = _find_project_root()
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_scripts")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end tests that call a real LLM API and build Docker images "
        "(slow, requires API key and Docker daemon)",
    )


def _has_api_key() -> bool:
    return bool(
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("GROQ_API_KEY")
    )


def pytest_collection_modifyitems(config, items):
    if not _has_api_key():
        skip_e2e = pytest.mark.skip(reason="No LLM API key configured (set OPENAI_API_KEY or ANTHROPIC_API_KEY)")
        for item in items:
            if item.get_closest_marker("e2e"):
                item.add_marker(skip_e2e)


@pytest.fixture(scope="session")
def project_root() -> str:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def scripts_dir() -> str:
    return SCRIPTS_DIR


@pytest.fixture
def run_tool(project_root):
    """Return a callable that invokes ``python -m dockerfile_gen.main <script_path>``."""

    def _run(script_path: str, timeout: int = 300) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "dockerfile_gen.main", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_root,
        )

    return _run
