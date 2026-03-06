from pydantic import BaseModel
from langchain_core.language_models import BaseChatModel

from dockerfile_gen.agent.state import AgentState


class DockerfileSpec(BaseModel):
    dockerfile: str
    test_args: str
    reasoning: str


SYSTEM_PROMPT = """\
You are an expert in writing Dockerfiles. Given a script, generate a minimal, working Dockerfile \
that wraps it, along with a representative test invocation.

Rules:
- Use the provided base image.
- COPY the script into the image at the working directory.
- Set a proper ENTRYPOINT so the script runs when the container starts and accepts arguments.
- Keep the Dockerfile minimal (no unnecessary layers).
- The test_args field must be ONLY the arguments to pass after `docker run --rm <image>`. \
  Do NOT include `docker run` or the image name — just the arguments to the script. \
  Example: if the script takes a text argument, test_args = '"Hello World"'
"""


def make_generate_node(llm: BaseChatModel):
    structured_llm = llm.with_structured_output(DockerfileSpec)

    def generate_dockerfile(state: AgentState) -> dict:
        prompt = (
            f"Script filename: {state['script_filename']}\n"
            f"Language: {state['language']}\n"
            f"Base image: {state['base_image']}\n\n"
            f"Script content:\n```\n{state['script_content']}\n```"
        )
        result: DockerfileSpec = structured_llm.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        return {
            "dockerfile": result.dockerfile,
            "test_args": result.test_args,
        }

    return generate_dockerfile
