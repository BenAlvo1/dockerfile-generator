# Architecture: AI-Powered Dockerfile Generator

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Component Breakdown](#3-component-breakdown)
4. [Data Flow & State Machine](#4-data-flow--state-machine)
5. [Security Model](#5-security-model)
6. [Testing Strategy](#6-testing-strategy)
7. [Known Limitations](#7-known-limitations)

---

## 1. System Overview

An AI-powered CLI tool that takes an arbitrary one-pager script (Python, JavaScript, Bash, Ruby, Go, Rust, Java, or unknown) and automatically:

1. **Validates** the script for malicious code and prompt injection.
2. **Selects** an appropriate Docker base image.
3. **Generates** a working Dockerfile via LLM.
4. **Builds and runs** the image against a representative test invocation.
5. **Self-corrects** on failure — up to `MAX_ATTEMPTS` times — by feeding build/run errors back to the LLM.

LLM-vendor-agnostic (OpenAI, Anthropic, Groq). Observable via Langfuse.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Host Machine                            │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              dockerfile-generator container              │   │
│  │                                                          │   │
│  │   CLI (main.py)                                          │   │
│  │       │                                                  │   │
│  │       ▼                                                  │   │
│  │   Config (pydantic-settings / .env)                      │   │
│  │       │                                                  │   │
│  │       ▼                                                  │   │
│  │   LLM Factory ──► OpenAI / Anthropic / Groq provider     │   │
│  │       │                                                  │   │
│  │       ▼                                                  │   │
│  │   LangGraph Agent                                        │   │
│  │   ┌─────────────────────────────────────────────────┐   │   │
│  │   │  parse_script → check_safety → fetch_base_image │   │   │
│  │   │       → generate_dockerfile → execute_dockerfile │   │   │
│  │   │       → validate_output ──────────────┐         │   │   │
│  │   │                    └──► reflect_and_fix ──────► │   │   │
│  │   │                         (+ Docker Hub API tool) │   │   │
│  │   └─────────────────────────────────────────────────┘   │   │
│  │       │                          │                       │   │
│  │       │ docker CLI calls          │ HTTPS                │   │
│  └───────┼──────────────────────────┼───────────────────────┘   │
│          │ /var/run/docker.sock      │                           │
│          ▼  (DooD mount)            ▼                           │
│   Docker daemon                 Docker Hub API                  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Langfuse stack (optional)                               │   │
│  │  langfuse + langfuse-worker + postgres + clickhouse +    │   │
│  │  redis + minio                                           │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Breakdown

### Entry Point — `main.py`

Single entry point registered as the `dockerfile-gen` console script. Parses `sys.argv`, loads `Config`, builds and invokes the LangGraph, then writes the Dockerfile on success.

**Exit codes:**
- `0` — success
- `1` — general failure (bad args, file not found, retries exhausted)
- `2` — safety block (malicious script or prompt injection)

### Configuration — `config.py`

Pydantic-settings `BaseSettings`, cached via `@lru_cache(maxsize=1)`.

| Field                  | Default       |
|------------------------|---------------|
| `llm_provider`         | `openai`      |
| `llm_model`            | `gpt-4o-mini` |
| `max_attempts`         | `10`          |
| `docker_build_timeout` | `120`s        |
| `docker_run_timeout`   | `30`s         |
| `langfuse_enabled`     | `False`       |

All fields are overridable via `.env` or environment variables.

### LLM Abstraction Layer

```
dockerfile_gen/llm/
  base.py              # LLMProvider ABC: create_model() -> BaseChatModel
  factory.py           # Dispatches to the right provider
  openai_provider.py / anthropic_provider.py / groq_provider.py
```

All providers return a `BaseChatModel`, keeping nodes vendor-agnostic. Structured output (`llm.with_structured_output(PydanticModel)`) is used throughout to avoid brittle string parsing. Tool binding (`llm.bind_tools(...)`) is used only in `reflect_and_fix`.

### LangGraph Agent

`agent/graph.py` defines a `StateGraph` over `AgentState` (a `TypedDict`).

**Graph topology:**

```
                  ┌───────────────┐
  (entry point)   │  parse_script │
                  └──────┬────────┘
                         │
                  ┌──────▼────────┐
                  │ check_safety  │
                  └──────┬────────┘
                         │
            ┌────────────▼──────────────┐
            │  _safety_gate (conditional)│
            └────────┬──────────────────┘
               safe  │        unsafe
                     │            └──► END (exit 2)
            ┌────────▼────────┐
            │ fetch_base_image│
            └────────┬────────┘
                     │
            ┌────────▼────────┐
            │generate_dockerfile│
            └────────┬────────┘
                     │
            ┌────────▼────────┐
            │execute_dockerfile│◄──────────────┐
            └────────┬────────┘               │
                     │                        │
            ┌────────▼────────┐               │
            │ validate_output │               │
            └────────┬────────┘               │
                     │                        │
        ┌────────────▼──────────────┐         │
        │  _should_retry (conditional)│        │
        └────────┬──────────────────┘         │
           end   │              reflect        │
                 │                  └──►┌──────┴──────────┐
                END                     │ reflect_and_fix  │
                                        └─────────────────┘
```

**Key `AgentState` fields:**

| Field            | Purpose                                                       |
|------------------|---------------------------------------------------------------|
| `script_content` | Raw UTF-8 content read by `parse_script`                      |
| `language`       | Detected language (e.g., `"python"`, `"unknown"`)             |
| `base_image`     | Docker base image (e.g., `python:3.12-slim`)                  |
| `dockerfile`     | Generated Dockerfile content                                  |
| `test_args`      | Arguments appended to `docker run --rm <tag>`                 |
| `build_output`   | Combined stdout+stderr from `docker build`                    |
| `run_output`     | Combined stdout+stderr from `docker run`                      |
| `exit_code`      | Exit code of the last `docker run` (or `-1` on timeout)       |
| `attempts`       | Number of execute attempts so far                             |
| `success`        | Set `True` by `validate_output` on a clean run                |
| `failure_stage`  | `"build"` / `"run"` / `"validation"`                         |
| `is_safe`        | `False` if blocked by safety node                             |
| `history`        | Per-attempt error snapshots fed to `reflect_and_fix`          |

### Agent Nodes

| Node | LLM cost | Notes |
|------|----------|-------|
| `parse_script` | Zero | Extension-based language detection; generates `image_tag` slug |
| `check_safety` | ~1 call (layer 2 only) | Regex pre-filter first; LLM semantic check if regex passes |
| `fetch_base_image` | Zero for known languages | Static `BASE_IMAGE_MAP`; LLM fallback for unknown extensions |
| `generate_dockerfile` | 1 call | Structured output: `DockerfileSpec(dockerfile, test_args, reasoning)` |
| `execute_dockerfile` | Zero | `docker build` + `docker run` in a `TemporaryDirectory` |
| `validate_output` | Zero | Non-zero exit code or error prefix in first line of output → failure |
| `reflect_and_fix` | 1 call | Sends full attempt history; binds `find_compatible_image` tool if image pull failure detected |

### Agent Tools

**`find_compatible_image`** (`agent/tools/docker_hub.py`) — LangChain `@tool` used only by `reflect_and_fix` when a base image pull failure is detected. Fetches Docker Hub v2 tags, resolves `latest` to its versioned digest sibling, and filters for useful variants (`slim`, `alpine`, `lts`, `jre`, `jdk`).

---

## 4. Data Flow & State Machine

```
User provides: script_path
                  │
                  ▼
         [parse_script]
         Reads file, detects language, generates image_tag slug.
                  │
                  ▼
         [check_safety]
         Regex pre-filter → (if blocked) → END (exit 2)
         LLM semantic check → (if blocked) → END (exit 2)
                  │ safe
                  ▼
         [fetch_base_image]
         Static map (known) or LLM inference (unknown) → base_image
                  │
                  ▼
         [generate_dockerfile]
         LLM: produces dockerfile + test_args
                  │
      ┌───────────▼────────────┐
      │    [execute_dockerfile] │ ◄────────────────────────────────┐
      │  docker build tmpdir    │                                   │
      │  docker run <test_args> │                                   │
      └───────────┬────────────┘                                   │
                  │                                                 │
      ┌───────────▼────────────┐                                   │
      │   [validate_output]    │                                   │
      │  exit_code == 0 AND    │                                   │
      │  no error prefixes     │                                   │
      └───────────┬────────────┘                                   │
                  │                                                 │
       success?   ├── YES ──► write Dockerfile to disk, exit 0     │
                  │                                                 │
                  └── NO ──► attempts < MAX_ATTEMPTS?              │
                               │                                    │
                               ├── YES ──► [reflect_and_fix] ──────┘
                               │           LLM: corrected dockerfile
                               │           + (optional) Docker Hub tool call
                               │
                               └── NO  ──► exit 1
```

---

## 5. Security Model

### Two-Layer Defense

All script content flows through `check_safety` before any LLM generation:

```
Script content
     │
     ▼
┌─────────────────────────────────────────────┐
│ Layer 1: Regex pre-filter (deterministic)   │
│  12 malicious patterns + 11 injection       │
│  patterns. O(n), zero LLM cost.             │
└─────────────────────────────────────────────┘
     │ passes
     ▼
┌─────────────────────────────────────────────┐
│ Layer 2: LLM semantic analysis              │
│  Catches obfuscated payloads and            │
│  high-level intent (e.g., credential        │
│  harvesters using only stdlib calls).       │
└─────────────────────────────────────────────┘
     │ safe
     ▼
  Proceed to base image fetch
```

### Container Isolation

- Each build/run uses a fresh `tempfile.TemporaryDirectory`, cleaned up regardless of outcome.
- `docker run` uses `--rm`; no containers persist.
- Generated images are prefixed `jit-gen-` for easy identification.

### Known Security Gaps

- No resource limits (`--memory`, `--cpus`) on `docker run`.
- DooD (Docker socket mount) grants host daemon-level privileges to the generator container. True isolation requires DinD or a BuildKit sidecar.
- Built images accumulate on the host and are not auto-cleaned.

---

## 6. Testing Strategy

```
┌────────────────────────────────────────────────────────────────────┐
│                         Test Pyramid                               │
│                                                                    │
│   ┌────────────────────────────────────────────────────────────┐  │
│   │         E2E (pytest -m e2e)                                │  │
│   │  Real LLM + real Docker. Slow (60-300s each).              │  │
│   │  - TestFullPipeline: word_reverser, vowel_counter,         │  │
│   │    line_counter, matrix_stats                              │  │
│   │  - TestLLMSafetyCheck: credential harvester bypasses       │  │
│   │    regex, caught by LLM                                    │  │
│   └────────────────────────────────────────────────────────────┘  │
│                                                                    │
│   ┌────────────────────────────────────────────────────────────┐  │
│   │         Integration (no LLM, no Docker)                    │  │
│   │  - TestSafetyBlocking: 8 malicious/injection scripts       │  │
│   │    blocked at regex layer (< 5s each)                      │  │
│   │  - TestCLIArgHandling: bad args, missing files             │  │
│   └────────────────────────────────────────────────────────────┘  │
│                                                                    │
│   ┌────────────────────────────────────────────────────────────┐  │
│   │         Unit Tests (no LLM, no Docker)                     │  │
│   │  test_parse_script, test_check_safety, test_validate_output│  │
│   │  test_fetch_base_image, test_docker_hub, test_reflect_and  │  │
│   │  _fix, test_config                                         │  │
│   └────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

**Test scripts** (`tests/integration/test_scripts/`):

| Directory           | Purpose                                                          |
|---------------------|------------------------------------------------------------------|
| `word_reverser/`    | Python — no deps                                                 |
| `vowel_counter/`    | JavaScript (Node.js)                                             |
| `line_counter/`     | Bash                                                             |
| `matrix_stats/`     | Python + numpy — tests pip dep installation                      |
| `malicious/`        | Fork bomb, reverse shell, curl dropper, crypto miner, disk wipe  |
| `prompt_injection/` | Instruction override, system tag, role reassignment              |
| `llm_safety_bypass/`| Credential harvester — passes regex, caught by LLM               |

---

## 7. Known Limitations

- **Docker access (DooD):** Socket mount gives the container host daemon-level privileges. Images accumulate on the host with no auto-cleanup.
- **Language detection:** Extension-only; shebangs are ignored. Unknown extensions fall back to LLM inference.
- **Single-file only:** Multi-file projects with `requirements.txt`, `package.json`, etc. are not supported.
- **No caching:** Each invocation calls the LLM from scratch regardless of prior runs on the same script.
- **Synchronous:** No progress reporting during long builds; no concurrent script processing.
- **CLI surface:** All config is env-var only; no CLI flags.

---