import logging
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

from dockerfile_gen.config import get_config
from dockerfile_gen.llm.factory import create_model
from dockerfile_gen.agent.graph import build_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _setup_langfuse(config) -> dict:
    if not config.langfuse_enabled:
        return {}
    from langfuse.langchain import CallbackHandler
    os.environ["LANGFUSE_PUBLIC_KEY"] = config.langfuse_public_key
    os.environ["LANGFUSE_SECRET_KEY"] = config.langfuse_secret_key
    os.environ["LANGFUSE_HOST"] = config.langfuse_host
    handler = CallbackHandler()
    logger.info("Langfuse tracing enabled at %s", config.langfuse_host)
    return {"callbacks": [handler]}


def _flush_langfuse(config) -> None:
    if not config.langfuse_enabled:
        return
    try:
        from langfuse._client.get_client import get_client
        get_client().shutdown()
    except Exception:
        logger.warning("Failed to flush Langfuse traces", exc_info=True)


def main():
    if len(sys.argv) != 2:
        logger.error("Usage: python -m dockerfile_gen.main <script_path>")
        sys.exit(1)

    script_path = sys.argv[1]

    if not os.path.isfile(script_path):
        logger.error("File not found: %s", script_path)
        sys.exit(1)

    config = get_config()
    logger.info("Generating Dockerfile for: %s", script_path)
    logger.info("Provider: %s / %s (max attempts: %d)", config.llm_provider, config.llm_model, config.max_attempts)

    try:
        llm = create_model(config)
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        sys.exit(1)
    graph = build_graph(llm)

    initial_state = {
        "script_path": script_path,
        "script_content": "",
        "script_filename": "",
        "language": "",
        "base_image": "",
        "image_tag": "",
        "dockerfile": "",
        "test_args": "",
        "build_output": "",
        "run_output": "",
        "exit_code": -1,
        "error": None,
        "attempts": 0,
        "success": False,
        "failure_stage": "",
        "is_safe": True,
        "safety_error": None,
        "history": [],
    }

    final_state = graph.invoke(initial_state, config=_setup_langfuse(config))
    _flush_langfuse(config)

    if not final_state["is_safe"]:
        if final_state.get("safety_error"):
            logger.error("Blocked: script failed safety check. Reason: %s", final_state["safety_error"])
            sys.exit(2)
        else:
            logger.error("Failed: %s", final_state["error"])
            sys.exit(1)

    if final_state["success"]:
        logger.info("Dockerfile generated and validated successfully (attempt %d).", final_state["attempts"])
        logger.info("Dockerfile contents:\n%s", final_state["dockerfile"])

        output_path = os.path.join(os.path.dirname(os.path.abspath(script_path)), "Dockerfile")
        with open(output_path, "w") as f:
            f.write(final_state["dockerfile"])
        logger.info("Dockerfile written to: %s", output_path)
        logger.info("Test with: docker run --rm %s %s", final_state["image_tag"], final_state["test_args"])
    else:
        logger.error("Failed after %d attempt(s). Error: %s", final_state["attempts"], final_state["error"])
        sys.exit(1)


if __name__ == "__main__":
    main()
