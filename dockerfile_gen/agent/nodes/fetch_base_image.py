from pydantic import BaseModel
from langchain_core.language_models import BaseChatModel

from dockerfile_gen.agent.state import AgentState

BASE_IMAGE_MAP = {
    "python": "python:3.12-slim",
    "javascript": "node:20-slim",
    "typescript": "node:20-slim",
    "bash": "alpine:3.19",
    "ruby": "ruby:3.3-slim",
    "go": "golang:1.22-alpine",
    "rust": "rust:1.77-slim",
    "java": "eclipse-temurin:21-jre-alpine",
}

SYSTEM_PROMPT = """\
You are an expert in Docker base images. Given a script's content and filename, select the most \
appropriate public Docker base image to run it.

Rules:
- Prefer slim or alpine variants for smaller image size.
- Use the shebang line, imports, syntax, and filename as signals.
- If the script requires a specific runtime version, reflect that in the image tag.
- Return only a well-known, publicly available image:tag.
"""


class BaseImageSpec(BaseModel):
    base_image: str
    reasoning: str


def make_fetch_base_image_node(llm: BaseChatModel):
    structured_llm = llm.with_structured_output(BaseImageSpec)

    def fetch_base_image(state: AgentState) -> dict:
        language = state["language"]

        if language in BASE_IMAGE_MAP:
            return {"base_image": BASE_IMAGE_MAP[language]}

        # Unknown language — ask the LLM to infer from script content
        prompt = (
            f"Script filename: {state['script_filename']}\n\n"
            f"Script content:\n```\n{state['script_content']}\n```"
        )
        result: BaseImageSpec = structured_llm.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        return {"base_image": result.base_image}

    return fetch_base_image
