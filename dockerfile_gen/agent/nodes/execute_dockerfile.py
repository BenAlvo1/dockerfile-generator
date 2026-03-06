import os
import shlex
import subprocess
import tempfile
from typing import Callable

from dockerfile_gen.agent.state import AgentState
from dockerfile_gen.config import Config


def make_execute_node(config: Config) -> Callable[[AgentState], dict]:
    def execute_dockerfile(state: AgentState) -> dict:
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "Dockerfile"), "w") as f:
                f.write(state["dockerfile"])

            with open(os.path.join(tmpdir, state["script_filename"]), "w") as f:
                f.write(state["script_content"])

            try:
                build_result = subprocess.run(
                    ["docker", "build", "-t", state["image_tag"], tmpdir],
                    capture_output=True,
                    text=True,
                    timeout=config.docker_build_timeout,
                )
            except subprocess.TimeoutExpired:
                return {
                    "build_output": "Docker build timed out.",
                    "run_output": "",
                    "exit_code": -1,
                    "failure_stage": "build",
                    "success": False,
                    "error": f"Docker build timed out after {config.docker_build_timeout}s.",
                    "attempts": state["attempts"] + 1,
                }
            build_output = build_result.stdout + build_result.stderr

            if build_result.returncode != 0:
                return {
                    "build_output": build_output,
                    "run_output": "",
                    "exit_code": build_result.returncode,
                    "failure_stage": "build",
                    "success": False,
                    "error": f"Docker build failed:\n{build_output}",
                    "attempts": state["attempts"] + 1,
                }

        run_cmd = ["docker", "run", "--rm", state["image_tag"]] + shlex.split(state["test_args"])
        try:
            run_result = subprocess.run(
                run_cmd,
                capture_output=True,
                text=True,
                timeout=config.docker_run_timeout,
            )
        except subprocess.TimeoutExpired:
            return {
                "build_output": build_output,
                "run_output": "Docker run timed out.",
                "exit_code": -1,
                "failure_stage": "run",
                "success": False,
                "error": f"Docker run timed out after {config.docker_run_timeout}s.",
                "attempts": state["attempts"] + 1,
            }
        run_output = run_result.stdout + run_result.stderr

        failure_stage = "" if run_result.returncode == 0 else "run"
        error = (
            None
            if run_result.returncode == 0
            else f"Docker run failed (exit {run_result.returncode}):\n{run_output}"
        )

        return {
            "build_output": build_output,
            "run_output": run_output,
            "exit_code": run_result.returncode,
            "failure_stage": failure_stage,
            "success": False,  # validate_output decides this
            "error": error,
            "attempts": state["attempts"] + 1,
        }

    return execute_dockerfile
