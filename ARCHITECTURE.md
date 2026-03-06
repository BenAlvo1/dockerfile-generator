# Architecture: AI-Powered Dockerfile Generator

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Component Breakdown](#3-component-breakdown)
   - 3.1 [Entry Point](#31-entry-point--mainpy)
   - 3.2 [Configuration](#32-configuration--configpy)
   - 3.3 [LLM Abstraction Layer](#33-llm-abstraction-layer)
   - 3.4 [LangGraph Agent](#34-langgraph-agent)
   - 3.5 [Agent Nodes](#35-agent-nodes)
   - 3.6 [Agent Tools](#36-agent-tools)
4. [Data Flow & State Machine](#4-data-flow--state-machine)
5. [Security Model](#5-security-model)
6. [Observability](#6-observability)
7. [Testing Strategy](#7-testing-strategy)
8. [Known Limitations](#8-known-limitations)
9. [Future Improvements](#9-future-improvements)

---

## 1. System Overview

The Dockerfile Generator is an AI-powered CLI tool that takes an arbitrary one-pager script (Python, JavaScript, Bash, Ruby, Go, Rust, Java, or any unknown language) and fully automatically:

1. **Validates** the script for malicious code and prompt injection.
2. **Selects** an appropriate Docker base image.
3. **Generates** a working Dockerfile via LLM.
4. **Builds and runs** the image against a representative test invocation.
5. **Self-corrects** on failure — up to `MAX_ATTEMPTS` times — by feeding build/run errors back to the LLM.

The system is designed to be LLM-vendor-agnostic (OpenAI, Anthropic, Groq) and fully observable via Langfuse.

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

### 3.1 Entry Point — `main.py`

`dockerfile_gen/main.py` is the single entry point, registered as the `dockerfile-gen` console script in `pyproject.toml`.

**Responsibilities:**
- Parses `sys.argv` (exactly one positional argument: `<script_path>`).
- Loads `Config` and instantiates the LLM via `create_model()`.
- Builds the LangGraph compiled graph via `build_graph()`.
- Seeds the initial `AgentState` with all default values.
- Invokes the graph and interprets the terminal state.
- Writes the validated Dockerfile next to the source script on success.
- Emits structured log output and exits with a well-defined code:
  - `0` — success
  - `1` — general failure (bad args, file not found, build/run failure exhausted retries)
  - `2` — safety block (malicious script or prompt injection detected)

**Exit code contract** is verified by the integration test suite (`TestCLIArgHandling`, `TestSafetyBlocking`).

---

### 3.2 Configuration — `config.py`

`dockerfile_gen/config.py` uses **pydantic-settings** (`BaseSettings`) for type-safe, environment-driven configuration.

| Field                  | Type    | Default              | Source         |
|------------------------|---------|----------------------|----------------|
| `llm_provider`         | Literal | `openai`             | `.env` / env   |
| `llm_model`            | str     | `gpt-4o-mini`        | `.env` / env   |
| `openai_api_key`       | str     | `""`                 | `.env` / env   |
| `anthropic_api_key`    | str     | `""`                 | `.env` / env   |
| `groq_api_key`         | str     | `""`                 | `.env` / env   |
| `max_attempts`         | int     | `3`                  | `.env` / env   |
| `docker_build_timeout` | int     | `120` (seconds)      | `.env` / env   |
| `docker_run_timeout`   | int     | `30` (seconds)       | `.env` / env   |
| `langfuse_enabled`     | bool    | `False`              | `.env` / env   |
| `langfuse_public_key`  | str     | `""`                 | `.env` / env   |
| `langfuse_secret_key`  | str     | `""`                 | `.env` / env   |
| `langfuse_host`        | str     | `http://localhost:3000` | `.env` / env |

`get_config()` is decorated with `@lru_cache(maxsize=1)` so the config object is parsed once per process and shared across all callers.

---

### 3.3 LLM Abstraction Layer

```
dockerfile_gen/llm/
  base.py              # LLMProvider ABC: defines create_model() -> BaseChatModel
  factory.py           # create_model(config) dispatches to the right provider
  openai_provider.py   # Wraps langchain-openai ChatOpenAI
  anthropic_provider.py# Wraps langchain-anthropic ChatAnthropic
  groq_provider.py     # Wraps langchain-groq ChatGroq
```

**Design decisions:**
- All providers return a `langchain_core.language_models.BaseChatModel`, making every downstream node LLM-vendor-agnostic.
- Structured output (`llm.with_structured_output(PydanticModel)`) is used for every node that needs deterministic, typed responses from the LLM. This avoids brittle string parsing.
- Tool binding (`llm.bind_tools(...)`) is used only in `reflect_and_fix` when the base image may need replacement.
- Adding a new provider requires implementing `LLMProvider.create_model()` and adding a `case` branch in `factory.py` — no other changes needed.

---

### 3.4 LangGraph Agent

`dockerfile_gen/agent/graph.py` defines the control flow as a **LangGraph `StateGraph`** over `AgentState`.

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

**State (`AgentState`)** is a `TypedDict` that flows through every node. Key fields:

| Field            | Purpose                                                       |
|------------------|---------------------------------------------------------------|
| `script_path`    | Absolute path to the source script (user input)               |
| `script_content` | Raw UTF-8 content read by `parse_script`                      |
| `script_filename`| Basename, used in prompts and to COPY into the image          |
| `language`       | Detected language string (e.g., `"python"`, `"unknown"`)     |
| `base_image`     | Docker base image (e.g., `python:3.12-slim`)                  |
| `image_tag`      | Generated tag (e.g., `jit-gen-word-reverser:latest`)          |
| `dockerfile`     | Generated Dockerfile content                                  |
| `test_args`      | Arguments appended to `docker run --rm <tag>` for testing     |
| `build_output`   | Combined stdout+stderr from `docker build`                    |
| `run_output`     | Combined stdout+stderr from `docker run`                      |
| `exit_code`      | Exit code of the last `docker run` (or `-1` on timeout)       |
| `attempts`       | Number of execute attempts so far                             |
| `success`        | Set `True` by `validate_output` on a clean run                |
| `failure_stage`  | `"build"` / `"run"` / `"validation"` — scopes the error      |
| `is_safe`        | `False` if blocked by safety node                             |
| `safety_error`   | Human-readable reason for the safety block                    |
| `history`        | List of per-attempt error snapshots fed to `reflect_and_fix`  |

---

### 3.5 Agent Nodes

#### `parse_script`
- Reads the file from disk (UTF-8). Fails gracefully on `OSError` / `UnicodeDecodeError`.
- Detects language from file extension via a static `LANGUAGE_MAP` (`.py` → `python`, `.js` → `javascript`, `.sh` → `bash`, etc.). Unknown extensions become `"unknown"`.
- Generates a sanitized `image_tag` by lowercasing and replacing non-alphanumeric characters with `-`.
- **Zero LLM cost.**

#### `check_safety`
Two-layer defense in depth:

| Layer | Mechanism | Cost |
|-------|-----------|------|
| 1 — Regex pre-filter | Compiled `re` patterns for fork bombs, reverse shells, `rm -rf`, crypto miners, disk wipes, and 11 prompt-injection signatures | Zero |
| 2 — LLM semantic analysis | Structured LLM call returning `SafetyResult(is_safe, threat_type, reason)` | ~1 LLM call |

Layer 1 runs first; if it fires, the LLM is never called. Layer 2 catches semantically malicious scripts that evade regex (e.g., credential harvesters that use only standard library calls).

The node returns early to the `_safety_gate` conditional edge which routes to `END` without proceeding to image generation.

#### `fetch_base_image`
- Consults a static `BASE_IMAGE_MAP` for all known language keys.
- For unknown languages, makes a single structured LLM call asking it to infer the best public base image from the script's shebang, imports, and filename.
- Prefers `slim`/`alpine` variants per system prompt instructions.
- **Zero LLM cost for known languages.**

#### `generate_dockerfile`
- Single structured LLM call producing `DockerfileSpec(dockerfile, test_args, reasoning)`.
- System prompt enforces: use the provided base image, COPY script, set `ENTRYPOINT`, keep layers minimal.
- `test_args` is a string of arguments only (no `docker run` prefix) — this is explicitly enforced in the prompt to prevent double-quoting issues downstream.

#### `execute_dockerfile`
- Writes the Dockerfile and script to a `tempfile.TemporaryDirectory`.
- Runs `docker build -t <image_tag> <tmpdir>` via `subprocess.run` with a configurable timeout.
- On build success, runs `docker run --rm <image_tag> <test_args>` (split via `shlex.split`).
- Returns structured state updates covering both success and failure (with `failure_stage` set to `"build"` or `"run"`).
- **Requires Docker daemon access** (see [DooD / DinD section](#91-docker-access-dood-vs-dind)).

#### `validate_output`
- Gate 1: non-zero exit code → failure.
- Gate 2: regex scan of the first line of `run_output` for error prefixes (`usage:`, `error:`, `Traceback`, `SyntaxError`, `node:internal`, `command not found`, etc.).
- On clean pass, sets `success = True`, clearing the error field.

#### `reflect_and_fix`
- Accumulates all prior attempts in a `history` list sent back to the LLM as context ("do not repeat these fixes").
- Detects whether the failure looks like a base image pull error (`_looks_like_image_problem`) and, if so, invokes `llm.bind_tools([find_compatible_image])` before calling the structured LLM — enabling the LLM to query Docker Hub for valid tags before producing the corrected Dockerfile.
- Returns an updated `dockerfile`, `test_args`, and optionally an updated `base_image` if a different image was chosen.
- After `reflect_and_fix`, control returns to `execute_dockerfile` (not `generate_dockerfile`), keeping the full correction loop tight.

---

### 3.6 Agent Tools

#### `find_compatible_image` (`agent/tools/docker_hub.py`)
A LangChain `@tool` that queries the **Docker Hub v2 API**:

1. Fetches the 50 most recently updated tags for a given repository.
2. Resolves `latest` to its actual versioned digest sibling (avoids pinning to a floating tag).
3. Filters for useful variants (`slim`, `alpine`, `lts`, `jre`, `jdk`) and returns them as a newline-separated `image:tag` list.

This tool is only bound and called from `reflect_and_fix` when a base image pull/resolution failure is detected — keeping it out of the hot path.

---

## 4. Data Flow & State Machine

```
User provides: script_path
                  │
                  ▼
         [parse_script]
         Reads file content, detects language,
         generates image_tag slug.
                  │
                  ▼
         [check_safety]
         Regex pre-filter → (if blocked) → END (exit 2)
         LLM semantic check → (if blocked) → END (exit 2)
                  │ safe
                  ▼
         [fetch_base_image]
         Static map lookup → (known language) → base_image
         LLM inference → (unknown language) → base_image
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
                               │           + (optional) Docker Hub
                               │             tag lookup tool call
                               │
                               └── NO  ──► exit 1
```

---

## 5. Security Model

### 5.1 Input Sanitization

All user-provided input (the script path and content) flows through `check_safety` before any LLM generation occurs. This prevents both:

- **Script-level threats**: Malicious code that would be executed inside the container (fork bombs, reverse shells, disk wipers, crypto miners, data exfiltration).
- **Prompt injection**: Text crafted to hijack the LLM's behavior (role reassignment, instruction override, system prompt smuggling via code comments or strings).

### 5.2 Two-Layer Defense

```
Script content
     │
     ▼
┌─────────────────────────────────────────────┐
│ Layer 1: Regex pre-filter (deterministic)   │
│                                             │
│  12 compiled malicious patterns             │
│  11 compiled injection patterns             │
│  O(n) over script content — microseconds   │
│  Zero LLM cost, zero network calls         │
└─────────────────────────────────────────────┘
     │ passes
     ▼
┌─────────────────────────────────────────────┐
│ Layer 2: LLM semantic analysis              │
│                                             │
│  Structured prompt with a strict system     │
│  prompt asking for is_safe + threat_type    │
│  Catches: obfuscated payloads, high-level   │
│  intent (e.g., credential harvesters using  │
│  only stdlib calls)                         │
└─────────────────────────────────────────────┘
     │ safe
     ▼
  Proceed to base image fetch
```

### 5.3 Container Isolation

- Each `docker build` + `docker run` execution happens against a **fresh `tempfile.TemporaryDirectory`** that is cleaned up after the build step, regardless of success or failure.
- The `docker run` call uses `--rm` (auto-remove) to ensure no containers persist.
- Generated images are named with the `jit-gen-` prefix to make them easily identifiable.
- The tool itself runs with configurable timeouts for both build and run phases.

### 5.4 Current Gaps (see Future Improvements)

- No resource limits (`--memory`, `--cpus`) are applied to `docker run`.
- The Docker socket is mounted from the host (DooD), which carries privilege escalation risk.
- Image tags are not pinned after generation; `docker run` could theoretically pull an updated image.

---

## 6. Observability

The tool integrates with **Langfuse** for full LLM call tracing:

- Enabled via `LANGFUSE_ENABLED=true` in `.env`.
- A `langfuse.langchain.CallbackHandler` is registered as a LangChain callback and passed to the LangGraph `invoke()` call.
- Every LLM call in every node appears as a trace span in the Langfuse UI, including:
  - Prompt content (system + user messages)
  - Model response (structured output)
  - Latency and token counts
  - Tool calls from `reflect_and_fix`
- `_flush_langfuse()` is called before process exit to ensure all buffered traces are shipped.

**Langfuse stack** (defined in `docker-compose.yml`):

```
langfuse (Next.js app)
  ├── langfuse-worker (async job processor)
  ├── langfuse-db (PostgreSQL 15)
  ├── langfuse-clickhouse (ClickHouse 24.4 — analytics store)
  ├── langfuse-redis (Redis 7 — job queue)
  └── langfuse-minio (MinIO — blob/event storage)
```

---

## 7. Testing Strategy

The test suite is layered by dependency cost:

```
┌────────────────────────────────────────────────────────────────────┐
│                         Test Pyramid                               │
│                                                                    │
│   ┌────────────────────────────────────────────────────────────┐  │
│   │         E2E / Integration (pytest -m e2e)                  │  │
│   │  Real LLM + real Docker builds. Slow (60-300s each).       │  │
│   │  - TestFullPipeline: generates & validates Dockerfiles for │  │
│   │    word_reverser, vowel_counter, line_counter, matrix_stats│  │
│   │  - TestLLMSafetyCheck: semantic safety (credential         │  │
│   │    harvester bypasses regex, caught by LLM)                │  │
│   └────────────────────────────────────────────────────────────┘  │
│                                                                    │
│   ┌────────────────────────────────────────────────────────────┐  │
│   │         Safety & CLI Integration (no LLM, no Docker)       │  │
│   │  - TestSafetyBlocking: 8 malicious/injection scripts       │  │
│   │    blocked at regex layer (deterministic, < 5s each)       │  │
│   │  - TestCLIArgHandling: bad args, missing files             │  │
│   └────────────────────────────────────────────────────────────┘  │
│                                                                    │
│   ┌────────────────────────────────────────────────────────────┐  │
│   │         Unit Tests (no LLM, no Docker)                     │  │
│   │  - test_parse_script.py: language detection, slug gen      │  │
│   │  - test_check_safety.py: regex pattern coverage            │  │
│   │  - test_validate_output.py: exit code + error prefix rules │  │
│   │  - test_fetch_base_image.py: static map + LLM fallback     │  │
│   │  - test_docker_hub.py: tag fetch, latest resolution,       │  │
│   │    useful-tag filtering                                     │  │
│   │  - test_reflect_and_fix.py: tool-call flow, history concat │  │
│   │  - test_config.py: pydantic-settings field defaults        │  │
│   └────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

**Test scripts** live in `tests/integration/test_scripts/`:

| Directory           | Purpose                                                          |
|---------------------|------------------------------------------------------------------|
| `word_reverser/`    | Python — simple string manipulation, no deps                     |
| `vowel_counter/`    | JavaScript (Node.js) — string iteration                          |
| `line_counter/`     | Bash — reads stdin / file                                        |
| `matrix_stats/`     | Python + numpy — tests pip dependency installation in Dockerfile |
| `malicious/`        | Fork bomb, reverse shell, curl dropper, crypto miner, disk wipe  |
| `prompt_injection/` | Instruction override, system tag, role reassignment              |
| `llm_safety_bypass/`| Credential harvester — passes regex, caught by LLM layer         |

---

## 8. Known Limitations

### 8.1 Docker Access: DooD vs. DinD

**Current approach — Docker-outside-of-Docker (DooD):**

The generator container mounts the host's Docker socket:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

This means `docker build` and `docker run` calls inside the container actually execute against the **host Docker daemon**. Built images and containers appear on the host, not isolated inside the generator container.

**Risks:**
- A container running inside the generator can escape to the host Docker daemon and access or modify any container or image on the host.
- The container effectively runs with Docker daemon-level privileges.
- Images built by the tool accumulate on the host and are not automatically cleaned up.

**Alternative — Docker-in-Docker (DinD):**

True DinD runs a full Docker daemon inside the generator container (using the `docker:dind` sidecar image). This fully isolates the build environment from the host but introduces its own problems:
- Requires the container to run in `--privileged` mode (still a security concern, but blast radius is limited to the DinD daemon).
- Image layer caching does not persist between runs, making repeated builds slower.
- Network connectivity to the host and other containers requires extra configuration.

See [Future Improvements — Docker Isolation](#91-docker-isolation) for the recommended path forward.

### 8.2 Language Detection

Language detection relies solely on **file extension**. Scripts with:
- Non-standard extensions (e.g., a Python script saved as `.tool`) will fall through to the LLM fallback in `fetch_base_image`.
- No extension at all will be classified as `"unknown"`.
- Shebang lines (e.g., `#!/usr/bin/env python3`) are not inspected in `parse_script` — this signal is available in the content but unused.

### 8.3 Single-File Scripts Only

The tool is designed for **one-pager scripts**: it copies a single file into the image. Multi-file projects with relative imports, `requirements.txt`, `package.json`, `go.mod`, etc. are not supported.

### 8.4 No Output Caching

Each invocation generates a fresh Dockerfile from scratch. If the same script is re-submitted, the LLM is called again. There is no content-hash-based cache to skip redundant generation.

### 8.5 Blocking / Synchronous Execution

The entire pipeline is synchronous. For large images or slow network pulls, the process simply waits. There is no progress reporting during long `docker build` runs, and no ability to process multiple scripts concurrently.

### 8.6 Image Cleanup

Images built by the tool (prefixed `jit-gen-`) are left on the Docker daemon after the run. Over time this can consume significant disk space, especially during development with many retry cycles.

### 8.7 Minimal CLI Surface

`main.py` accepts exactly one positional argument: the script path. All other behavior is controlled via environment variables. There is no way to override configuration from the command line without modifying `.env`.

---

## 9. Future Improvements

### 9.1 Docker Isolation

**Recommended path: Rootless DinD with a BuildKit daemon**

Replace the DooD socket mount with a purpose-built BuildKit daemon running inside a sidecar container:

```yaml
services:
  buildkitd:
    image: moby/buildkit:latest
    privileged: true          # confined to this sidecar, not the host
    volumes:
      - buildkit_cache:/var/lib/buildkit

  dockerfile-generator:
    environment:
      - BUILDKIT_HOST=tcp://buildkitd:1234
    depends_on:
      - buildkitd
```

- **BuildKit** (`buildctl`) can build images entirely inside the sidecar and export them via OCI tarball. The host Docker daemon is never touched.
- Images built this way can be scanned and discarded without host impact.
- The generator container needs no special privileges — only the dedicated BuildKit sidecar runs privileged.
- Alternatively, **Kaniko** or **img** can build OCI images without any daemon and without privilege escalation.

### 9.2 CLI Flags

Expose all configuration as proper CLI flags using `argparse` or `click`, falling back to environment variables. Proposed interface:

```
dockerfile-gen [OPTIONS] <script_path>

Options:
  --provider {openai,anthropic,groq}  LLM provider [env: LLM_PROVIDER]
  --model TEXT                         Model name [env: LLM_MODEL]
  --max-attempts INT                   Retry limit [env: MAX_ATTEMPTS, default: 3]
  --build-timeout INT                  docker build timeout in seconds [default: 120]
  --run-timeout INT                    docker run timeout in seconds [default: 30]
  --output-dir PATH                    Write Dockerfile here instead of next to script
  --dry-run                            Generate Dockerfile but do not build or run
  --no-safety-check                    Skip safety analysis (trusted input, CI use)
  --tag TEXT                           Override the generated image tag
  --push                               Push the built image to a registry after validation
  --registry TEXT                      Registry prefix for --push (e.g. registry.example.com)
  --cleanup / --no-cleanup             Remove the built image after validation [default: --cleanup]
  --log-level {DEBUG,INFO,WARNING}     Logging verbosity [default: INFO]
  --langfuse / --no-langfuse           Override LANGFUSE_ENABLED
  -h, --help                           Show this message and exit
```

### 9.4 Multi-File / Project Support

Support bundling a directory rather than a single file:

- Accept a `--context-dir` that is passed as the Docker build context.
- Auto-detect `requirements.txt`, `package.json`, `go.mod`, `Cargo.toml`, `Gemfile` in the directory and instruct the LLM to include appropriate install steps.
- Allow specifying the **entrypoint script** within the context directory.

### 9.6 Output Caching

Compute a SHA-256 hash of the script content and store a mapping to the generated Dockerfile in a local cache (e.g., `~/.cache/dockerfile-gen/`). On subsequent runs with the same content, skip LLM generation and reuse the cached Dockerfile (with an optional `--force-regenerate` escape hatch).

### 9.7 Streaming Progress & Rich Output

Replace the plain `logging` output with a structured progress display (e.g., using `rich`):

```
[1/7] parse_script         ✓  language=python, tag=jit-gen-word-reverser
[2/7] check_safety         ✓  safe (regex + LLM)
[3/7] fetch_base_image     ✓  python:3.12-slim (static map)
[4/7] generate_dockerfile  ✓  6 instructions
[5/7] execute_dockerfile   ⟳  building... (23s)
[5/7] execute_dockerfile   ✓  build OK, run OK
[6/7] validate_output      ✓  exit 0, no error patterns
[7/7] write output         ✓  tests/integration/test_scripts/word_reverser/Dockerfile
```

This makes it far easier to diagnose where in the pipeline a failure occurs, especially for long Docker builds.

### 9.9 Parallel / Batch Processing

Add a batch mode that accepts multiple script paths and processes them concurrently using `asyncio` + `asyncio.subprocess`:

```
dockerfile-gen --batch scripts/*.py --workers 4 --output-dir ./dockerfiles/
```

Each script would get its own LangGraph invocation, with the LLM calls and Docker builds running in parallel up to `--workers`.

### 9.10 Additional LLM Providers

The `LLMProvider` ABC makes adding providers trivial. Candidates:

| Provider            | LangChain Package          | Notes                              |
|---------------------|----------------------------|------------------------------------|
| Google Gemini       | `langchain-google-genai`   | Gemini 2.x Flash for low cost      |
| AWS Bedrock         | `langchain-aws`            | For teams already on AWS IAM       |
| Azure OpenAI        | `langchain-openai` (Azure) | For enterprise Azure deployments   |
| Ollama (local)      | `langchain-ollama`         | Zero API cost, air-gapped use      |
| Mistral AI          | `langchain-mistralai`      | Strong European alternative        |

### 9.11 Structured Reporting

Add a machine-readable output mode (`--output-format json`) that writes a JSON result to stdout :

```json
{
  "success": true,
  "attempts": 1,
  "script_path": "/scripts/word_reverser.py",
  "dockerfile_path": "/scripts/Dockerfile",
  "image_tag": "jit-gen-word-reverser:latest",
  "test_args": "\"Hello World\""
}
```

This makes the tool composable in CI pipelines where downstream steps need to parse the result.

### 9.12 Safety Check Enhancements

- **Allow-list mode**: Accept a `--trusted` flag that skips the safety check entirely for internal/CI use where inputs are already vetted.
- **Custom regex rules**: Allow teams to supply additional `--safety-pattern` regexes for domain-specific threats.
- **Sandboxed static analysis**: Run the script through a lightweight static analyzer (e.g., `bandit` for Python, `semgrep` for multi-language) as a Layer 1.5 check before the LLM.

---

## Appendix: Directory Structure

```
jit-ai-challenge/
├── Dockerfile                        # Generator image definition
├── docker-compose.yml                # Compose: generator + Langfuse stack + test runner
├── pyproject.toml                    # Project metadata, deps, entry points, tool config
├── .env.example                      # Configuration template
│
├── dockerfile_gen/                   # Main package
│   ├── main.py                       # CLI entry point
│   ├── config.py                     # Pydantic-settings Config + get_config()
│   │
│   ├── llm/                          # LLM abstraction layer
│   │   ├── base.py                   # LLMProvider ABC
│   │   ├── factory.py                # create_model(config) dispatcher
│   │   ├── openai_provider.py
│   │   ├── anthropic_provider.py
│   │   └── groq_provider.py
│   │
│   └── agent/                        # LangGraph agent
│       ├── state.py                  # AgentState TypedDict
│       ├── graph.py                  # StateGraph definition + conditional edges
│       │
│       ├── nodes/                    # One module per graph node
│       │   ├── parse_script.py
│       │   ├── check_safety.py       # Regex pre-filter + LLM semantic check
│       │   ├── fetch_base_image.py   # Static map + LLM fallback
│       │   ├── generate_dockerfile.py
│       │   ├── execute_dockerfile.py # subprocess docker build + docker run
│       │   ├── validate_output.py    # Exit code + error prefix heuristics
│       │   └── reflect_and_fix.py   # LLM-driven correction + Docker Hub tool
│       │
│       └── tools/
│           └── docker_hub.py         # find_compatible_image LangChain @tool
│
└── tests/
    ├── test_parse_script.py
    ├── test_check_safety.py
    ├── test_validate_output.py
    ├── test_fetch_base_image.py
    ├── test_docker_hub.py
    ├── test_reflect_and_fix.py
    ├── test_config.py
    │
    └── integration/
        ├── Dockerfile.integration    # Integration test runner image
        ├── conftest.py               # run_tool fixture, project_root fixture
        ├── test_integration.py       # CLI, safety, full e2e, LLM safety tests
        └── test_scripts/
            ├── word_reverser/        # Python — no deps
            ├── vowel_counter/        # JavaScript
            ├── line_counter/         # Bash
            ├── matrix_stats/         # Python + numpy (pip dep test)
            ├── malicious/            # fork_bomb, reverse_shell, curl_exec, crypto_miner, disk_wipe
            ├── prompt_injection/     # inject_override, inject_system, inject_role_reassign
            └── llm_safety_bypass/    # credential_harvester (passes regex, caught by LLM)
```
