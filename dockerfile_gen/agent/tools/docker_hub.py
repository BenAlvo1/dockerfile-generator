import json
import urllib.error
import urllib.parse
import urllib.request

from langchain_core.tools import tool

_USEFUL_TAG_KEYWORDS = ("slim", "alpine", "lts", "jre", "jdk")


def _is_useful(tag: str) -> bool:
    """True if the tag contains a useful keyword as a whole word segment.

    Uses separator-boundary matching (e.g. '-' or start/end) to avoid
    false positives like 'lts' matching inside 'latest'.
    """
    parts = tag.replace(".", "-").split("-")
    return any(kw in parts for kw in _USEFUL_TAG_KEYWORDS)


def _resolve_latest(results: list[dict]) -> str | None:
    """Return the versioned tag that 'latest' currently points to, if any.

    Finds the digest of the 'latest' tag, then returns the first other tag
    that shares that digest and looks like a pinned version (contains a digit).
    """
    by_digest: dict[str, list[str]] = {}
    latest_digest: str | None = None

    for r in results:
        name = r.get("name", "")
        digest = r.get("digest") or ""
        if not digest:
            continue
        by_digest.setdefault(digest, []).append(name)
        if name == "latest":
            latest_digest = digest

    if not latest_digest:
        return None

    siblings = [t for t in by_digest.get(latest_digest, []) if t != "latest" and any(c.isdigit() for c in t)]
    return siblings[0] if siblings else None


def _fetch_tags(namespace: str, repo: str) -> list[str]:
    params = urllib.parse.urlencode({"page_size": 50, "ordering": "last_updated"})
    url = f"https://hub.docker.com/v2/repositories/{namespace}/{repo}/tags?{params}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    results = data.get("results", [])
    tags = [r["name"] for r in results]

    # Replace "latest" with the actual versioned tag it points to (if resolvable)
    resolved = _resolve_latest(results)
    if resolved:
        tags = [resolved if t == "latest" else t for t in tags]

    # Prefer slim/alpine/lts variants; fall back to all tags if none match
    useful = [t for t in tags if _is_useful(t)]
    return useful or tags


@tool(description="Search Docker Hub for available image tags")
def find_compatible_image(repo: str) -> str:
    """Search Docker Hub for available tags for a given image repository.

    Use this when the current base image is causing build or pull failures
    and you need to find a valid, publicly available image:tag.

    Args:
        repo: Docker Hub repository name, e.g. 'python', 'node', 'golang',
              'ubuntu', or 'bitnami/python'. For official library images,
              just the name is enough (e.g. 'python').

    Returns:
        Newline-separated list of image:tag strings available on Docker Hub.
    """
    repo = repo.strip().removeprefix("library/")

    if "/" in repo:
        namespace, name = repo.split("/", 1)
    else:
        namespace, name = "library", repo

    try:
        tags = _fetch_tags(namespace, name)
    except urllib.error.HTTPError as e:
        return f"Error: Docker Hub returned HTTP {e.code} for '{repo}'. Check the repository name."
    except Exception as e:
        return f"Error fetching tags for '{repo}': {e}"

    if not tags:
        return f"No tags found for '{repo}'."

    prefix = f"{namespace}/{name}" if namespace != "library" else name
    lines = [f"{prefix}:{t}" for t in tags]
    return "\n".join(lines)
