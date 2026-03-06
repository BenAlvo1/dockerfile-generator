import re

from pydantic import BaseModel
from langchain_core.language_models import BaseChatModel

from dockerfile_gen.agent.state import AgentState
from dockerfile_gen.agent.tools.docker_hub import find_compatible_image


class FixedSpec(BaseModel):
    dockerfile: str
    test_args: str
    analysis: str


SYSTEM_PROMPT = """\
You are an expert Docker debugger. A Dockerfile generated for a script has failed.
Analyze the error and produce a corrected Dockerfile and test invocation.

Focus on:
- Build failures: missing packages, wrong base image, wrong COPY paths, permission issues.
- Run failures: wrong ENTRYPOINT/CMD, missing runtime dependencies, incorrect argument passing.
- Validation failures: test_args that don't match the script's expected input format.

If the base image is the problem (pull error, wrong platform, non-existent tag), use the
find_compatible_image tool to look up valid tags before writing the corrected Dockerfile.

Return only the corrected dockerfile and test_args (just the script arguments, not `docker run`).
"""


def _extract_base_image(dockerfile: str) -> str | None:
    match = re.search(r"^FROM\s+(\S+)", dockerfile, re.MULTILINE | re.IGNORECASE)
    return match.group(1) if match else None


_IMAGE_PULL_ERRORS = ("pull access denied", "not found", "manifest unknown", "no match for platform", "does not exist")


def _looks_like_image_problem(state: AgentState) -> bool:
    """True only when the build output suggests a base image pull/resolution failure."""
    if state["failure_stage"] != "build":
        return False
    output = (state["build_output"] or "").lower()
    return any(kw in output for kw in _IMAGE_PULL_ERRORS)


def make_reflect_node(llm: BaseChatModel):
    llm_with_tools = llm.bind_tools([find_compatible_image])
    structured_llm = llm.with_structured_output(FixedSpec)

    def reflect_and_fix(state: AgentState) -> dict:
        prior_attempts = state.get("history", [])
        history_section = ""
        if prior_attempts:
            lines = ["Previous failed attempts (do not repeat these fixes):\n"]
            for i, entry in enumerate(prior_attempts, 1):
                lines.append(f"--- Attempt {i} ---")
                lines.append(f"Failure stage: {entry['failure_stage']}")
                lines.append(f"Dockerfile tried:\n```dockerfile\n{entry['dockerfile']}\n```")
                lines.append(f"Error:\n{entry['error']}")
                lines.append(f"Analysis: {entry['analysis']}\n")
            history_section = "\n".join(lines) + "\n\n"

        user_content = (
            f"Script ({state['script_filename']}):\n```\n{state['script_content']}\n```\n\n"
            f"Base image: {state['base_image']}\n\n"
            f"{history_section}"
            f"Current failed Dockerfile:\n```dockerfile\n{state['dockerfile']}\n```\n\n"
            f"Test args used: {state['test_args']}\n"
            f"Failure stage: {state['failure_stage']}\n\n"
            f"Build output:\n{state['build_output']}\n\n"
            f"Run output:\n{state['run_output']}\n\n"
            f"Error: {state['error']}"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        if _looks_like_image_problem(state):
            response = llm_with_tools.invoke(messages)
            if response.tool_calls:
                messages.append(response)
                for tc in response.tool_calls:
                    tool_result = find_compatible_image.invoke(tc["args"])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": str(tool_result),
                    })

        result: FixedSpec = structured_llm.invoke(messages)

        updates: dict = {
            "dockerfile": result.dockerfile,
            "test_args": result.test_args,
            "history": prior_attempts + [{
                "dockerfile": state["dockerfile"],
                "failure_stage": state["failure_stage"],
                "build_output": state["build_output"],
                "run_output": state["run_output"],
                "error": state["error"],
                "analysis": result.analysis,
            }],
        }

        new_image = _extract_base_image(result.dockerfile)
        if new_image and new_image != state["base_image"]:
            updates["base_image"] = new_image

        return updates

    return reflect_and_fix
