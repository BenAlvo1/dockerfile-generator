from pydantic import BaseModel
from langchain_core.language_models import BaseChatModel

from dockerfile_gen.agent.state import AgentState


SYSTEM_PROMPT = """\
You are an expert in Docker and software dependencies. Given a script's content and filename, \
identify all technologies required to run it inside a Docker container.

Rules:
- Choose the most appropriate base image (prefer slim or alpine variants).
- List system packages that must be installed via the OS package manager (apk/apt), \
  e.g. ["bash", "curl", "git"].
- List runtime packages that must be installed via a language package manager, \
  e.g. ["requests", "numpy"] for pip, ["axios"] for npm. Use plain package names only.
- Use the shebang line, imports, filename extension, and syntax as signals.
- Be exhaustive — missing packages are the primary cause of container build failures.
"""


class TechnologySpec(BaseModel):
    base_image: str
    system_packages: list[str]
    runtime_packages: list[str]
    reasoning: str


def make_identify_technologies_node(llm: BaseChatModel):
    structured_llm = llm.with_structured_output(TechnologySpec)

    def identify_technologies(state: AgentState) -> dict:
        prompt = (
            f"Script filename: {state['script_filename']}\n"
            f"Language: {state['language']}\n\n"
            f"Script content:\n```\n{state['script_content']}\n```"
        )
        result: TechnologySpec = structured_llm.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        return {
            "base_image": result.base_image,
            "system_packages": result.system_packages,
            "runtime_packages": result.runtime_packages,
        }

    return identify_technologies
