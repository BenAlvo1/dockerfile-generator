import os
import re

from dockerfile_gen.agent.state import AgentState

LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".sh": "bash",
    ".rb": "ruby",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}


def parse_script(state: AgentState) -> dict:
    path = state["script_path"]

    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return {"error": f"Cannot read script: {e}", "is_safe": False}
    except UnicodeDecodeError as e:
        return {"error": f"Script is not valid UTF-8 text: {e}", "is_safe": False}

    filename = os.path.basename(path)
    ext = os.path.splitext(filename)[1].lower()
    language = LANGUAGE_MAP.get(ext, "unknown")

    slug = re.sub(r"[^a-z0-9-]", "-", os.path.splitext(filename)[0].lower())
    image_tag = f"jit-gen-{slug}:latest"

    return {
        "script_content": content,
        "script_filename": filename,
        "language": language,
        "image_tag": image_tag,
    }
