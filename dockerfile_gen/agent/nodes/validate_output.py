import logging
import re

from dockerfile_gen.agent.state import AgentState

logger = logging.getLogger(__name__)

_ERROR_PATTERNS = [
    r"^usage:",
    r"^error:",
    r"^traceback \(most recent call last\)",
    r"^syntaxerror:",
    r"^typeerror:",
    r"^exception:",
    r"^node:internal",
    r"^bash:.*command not found",
]
_COMPILED_ERROR_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _ERROR_PATTERNS]


def _looks_like_error(output: str) -> bool:
    first_line = output.strip().splitlines()[0] if output.strip() else ""
    return any(p.match(first_line) for p in _COMPILED_ERROR_PATTERNS)


def validate_output(state: AgentState) -> dict:
    # Gate 1: non-zero exit code
    if state["exit_code"] != 0:
        logger.debug("Validation failed: non-zero exit code %d", state["exit_code"])
        return {"success": False, "failure_stage": state["failure_stage"]}

    # Gate 2: output looks like an error/usage message
    if _looks_like_error(state["run_output"]):
        msg = f"Container exited 0 but output looks like an error: {state['run_output'][:200]!r}"
        logger.debug(msg)
        return {"success": False, "error": msg, "failure_stage": "validation"}

    logger.debug("Validation passed.")
    return {"success": True, "error": None, "failure_stage": ""}
