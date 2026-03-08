from typing import TypedDict


class AgentState(TypedDict):
    script_path: str
    script_content: str
    script_filename: str
    language: str
    base_image: str
    system_packages: list[str]
    runtime_packages: list[str]
    image_tag: str
    dockerfile: str
    test_args: str          # args appended to `docker run --rm <image_tag>` for testing
    build_output: str
    run_output: str
    exit_code: int
    error: str | None
    attempts: int           # number of execute attempts so far
    success: bool
    failure_stage: str      # "build" | "run" | "validation"
    is_safe: bool
    safety_error: str | None
    history: list[dict]         # per-attempt error context accumulated by reflect_and_fix
