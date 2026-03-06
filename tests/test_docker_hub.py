import json
import urllib.error
from unittest.mock import MagicMock, patch

from dockerfile_gen.agent.tools.docker_hub import find_compatible_image, _resolve_latest


def _make_results(tags: list[str], latest_alias: str | None = None) -> list[dict]:
    """Build a fake Docker Hub results list.

    If latest_alias is given, 'latest' and that tag share the same digest,
    simulating Docker Hub's behaviour where 'latest' is an alias for a version tag.
    """
    shared_digest = "sha256:aabbccdd"
    results = []
    for t in tags:
        digest = shared_digest if (latest_alias and t in ("latest", latest_alias)) else f"sha256:{t}"
        results.append({"name": t, "digest": digest})
    return results


def _mock_urlopen(tags: list[str], latest_alias: str | None = None):
    """Context-manager mock returning a fake Docker Hub tags response."""
    payload = json.dumps({"results": _make_results(tags, latest_alias)}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = payload
    return mock_resp


# ---------------------------------------------------------------------------
# Tag filtering
# ---------------------------------------------------------------------------

def test_returns_slim_and_alpine_tags_when_available():
    tags = ["3.12-slim", "3.11-slim", "3.12-alpine", "3.12"]
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(tags)):
        result = find_compatible_image.invoke({"repo": "python"})
    lines = result.strip().splitlines()
    assert "python:3.12-slim" in lines
    assert "python:3.12-alpine" in lines
    # Bare version tags without useful keywords are excluded
    assert "python:3.12" not in lines


def test_falls_back_to_all_tags_when_no_useful_keywords_match():
    tags = ["3.12", "3.11", "3.10"]
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(tags)):
        result = find_compatible_image.invoke({"repo": "python"})
    lines = result.strip().splitlines()
    assert "python:3.12" in lines
    assert "python:3.11" in lines
    assert "python:3.10" in lines


def test_lts_tag_is_considered_useful():
    tags = ["lts", "18", "20"]
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(tags)):
        result = find_compatible_image.invoke({"repo": "node"})
    lines = result.strip().splitlines()
    assert "node:lts" in lines
    # Bare version numbers without useful keywords are excluded
    assert "node:18" not in lines
    assert "node:20" not in lines


# ---------------------------------------------------------------------------
# latest → versioned tag resolution
# ---------------------------------------------------------------------------

def test_resolve_latest_returns_versioned_tag():
    results = _make_results(["latest", "3.19", "3.18"], latest_alias="3.19")
    assert _resolve_latest(results) == "3.19"


def test_resolve_latest_returns_none_when_no_sibling():
    results = _make_results(["latest", "edge"])  # "edge" has no digit
    assert _resolve_latest(results) is None


def test_resolve_latest_returns_none_when_latest_absent():
    results = _make_results(["3.19", "3.18"])
    assert _resolve_latest(results) is None


def test_latest_replaced_by_versioned_tag_in_output():
    tags = ["latest", "3.19", "3.18"]
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(tags, latest_alias="3.19")):
        result = find_compatible_image.invoke({"repo": "alpine"})
    lines = result.strip().splitlines()
    assert "alpine:latest" not in lines
    assert "alpine:3.19" in lines


def test_latest_kept_when_no_versioned_alias_found():
    """If 'latest' has no versioned sibling, it stays in the results."""
    tags = ["latest", "edge"]
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(tags)):
        result = find_compatible_image.invoke({"repo": "alpine"})
    # No versioned alias → falls back to all tags unchanged
    assert "alpine:latest" in result or "alpine:edge" in result


def test_empty_results_returns_no_tags_message():
    with patch("urllib.request.urlopen", return_value=_mock_urlopen([])):
        result = find_compatible_image.invoke({"repo": "python"})
    assert "No tags found" in result


# ---------------------------------------------------------------------------
# Namespace handling
# ---------------------------------------------------------------------------

def test_official_image_uses_library_namespace():
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(["3.12-slim"])) as mock_open:
        find_compatible_image.invoke({"repo": "python"})
    called_url = mock_open.call_args[0][0].full_url
    assert "library/python" in called_url


def test_library_prefix_stripped_before_lookup():
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(["3.12-slim"])) as mock_open:
        find_compatible_image.invoke({"repo": "library/python"})
    # Should use library namespace, not double "library/library/python"
    called_url = mock_open.call_args[0][0].full_url
    assert "library/python" in called_url
    assert "library/library" not in called_url


def test_custom_namespace_preserved():
    with patch("urllib.request.urlopen", return_value=_mock_urlopen(["1.0-slim"])) as mock_open:
        find_compatible_image.invoke({"repo": "bitnami/python"})
    called_url = mock_open.call_args[0][0].full_url
    assert "bitnami/python" in called_url


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_http_404_returns_descriptive_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
        url="", code=404, msg="Not Found", hdrs=None, fp=None
    )):
        result = find_compatible_image.invoke({"repo": "nonexistent-xyz"})
    assert "Error" in result
    assert "404" in result


def test_connection_error_returns_descriptive_error():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        result = find_compatible_image.invoke({"repo": "python"})
    assert "Error" in result
