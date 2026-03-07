# Dockerfile Generator

An AI-powered tool that takes any script and automatically generates, builds, tests, and self-corrects a Dockerfile for it. Supports Python, JavaScript/TypeScript, Bash, Ruby, Go, Rust, and Java — and falls back to LLM-inferred base images for unknown languages.

## How it works

```
parse_script → check_safety → fetch_base_image → generate_dockerfile
                                                         ↓
                                                 execute_dockerfile
                                                         ↓
                                                  validate_output
                                                   ↙          ↘
                                                done     reflect_and_fix
                                                              ↓
                                                      execute_dockerfile (retry)
```

1. **parse_script** — detects language from file extension and generates an image tag
2. **check_safety** — two-layer check: fast regex pre-filter, then LLM semantic analysis to block malicious scripts and prompt injection
3. **fetch_base_image** — static map for known languages (zero LLM cost); LLM-inferred from script content for unknown extensions
4. **generate_dockerfile** — LLM generates a working Dockerfile with test args
5. **execute_dockerfile** — runs `docker build` then `docker run`
6. **validate_output** — checks exit code and output for errors
7. **reflect_and_fix** — on failure, analyzes the error and retries (up to `MAX_ATTEMPTS`); can call the Docker Hub API to find a valid replacement base image when the current one fails

## Prerequisites

- Docker with Compose
- An API key for one of the supported LLM providers (OpenAI, Anthropic, or Groq)

## Setup

```bash
git clone <repo>
cd jit-ai-challenge

cp .env.example .env
# Fill in your API key
```

### Configuration

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai`, `anthropic`, or `groq` |
| `LLM_MODEL` | `gpt-4o-mini` | Model name for the chosen provider |
| `OPENAI_API_KEY` | — | Required if using OpenAI |
| `ANTHROPIC_API_KEY` | — | Required if using Anthropic |
| `GROQ_API_KEY` | — | Required if using Groq |
| `MAX_ATTEMPTS` | `3` | Max build+fix retry attempts |
| `DOCKER_BUILD_TIMEOUT` | `120` | Docker build timeout (seconds) |
| `DOCKER_RUN_TIMEOUT` | `30` | Docker run timeout (seconds) |
| `LANGFUSE_ENABLED` | `false` | Enable Langfuse observability |
| `LANGFUSE_HOST` | `http://localhost:3000` | Langfuse server URL |

## Usage

Build the image first:

```bash
docker compose build dockerfile-generator
```

Run against a script:

```bash
docker compose run --no-deps \
  -v $(pwd):/scripts \
  dockerfile-generator \
  /scripts/tests/integration/test_scripts/word_reverser/word_reverser.py
```

Replace the script path with any supported script. The generated `Dockerfile` is written to the same directory as the input script.

On success:

```
Dockerfile generated and validated successfully (attempt 1).
Dockerfile written to: tests/integration/test_scripts/word_reverser/Dockerfile
Test with: docker run --rm jit-gen-word-reverser:latest "Hello World"
```

## Observability (Langfuse)

Start the Langfuse stack:

```bash
docker compose up -d \
  langfuse-db langfuse-clickhouse langfuse-redis langfuse-minio \
  langfuse langfuse-worker
```

Update `.env`:

```env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-local-00000000
LANGFUSE_SECRET_KEY=sk-lf-local-00000000
LANGFUSE_HOST=http://langfuse:3000
```

Then run the tool:

```bash
docker compose run \
  -v $(pwd):/scripts \
  dockerfile-generator \
  /scripts/tests/integration/test_scripts/word_reverser/word_reverser.py
```

Open `http://localhost:3000` to view traces (`admin@local.dev` / `admin1234`).

## Running tests

### Unit tests

```bash
uv venv
uv pip install -e ".[dev]"
uv run pytest
```

### Integration tests

| Tier | Needs LLM? | Needs Docker builds? |
|---|---|---|
| Unit tests | No | No |
| Safety / CLI checks | No | No |
| Full e2e pipeline | Yes | Yes |
| LLM semantic safety | Yes | No |

**Unit tests (no API key or Docker required):**

```bash
uv venv
uv pip install -e ".[dev]"
uv run pytest tests/ -v --ignore=tests/integration
```

Covers: config, script parsing, safety regex layer, base image selection (static map + LLM fallback), Docker Hub tag lookup, and the `reflect_and_fix` tool-call flow.

**Safety tests only (no API key required):**

```bash
docker compose --profile test run --rm integration-tests
```

Verifies that malicious scripts (fork bombs, reverse shells, crypto miners, disk wipers) and prompt-injection attempts are blocked before the LLM is called.

**Full e2e tests:**

```bash
docker compose --profile test run --rm integration-tests \
  python -m pytest tests/integration/ -v
```

Calls the real LLM, builds and runs Docker images for each bundled script (including the `matrix_stats` script that requires numpy), exercises the reflect-and-fix retry loop, and verifies that the LLM semantic safety check catches obfuscated threats that bypass the regex filter (e.g. credential harvesters).

## Project structure

```
dockerfile-generator/
├── Dockerfile                        # Generator image definition
├── docker-compose.yml                # Compose: generator + Langfuse stack
├── pyproject.toml                    # Project metadata, deps, entry points
├── .env.example                      # Configuration template
│
├── dockerfile_gen/
│   ├── main.py                       # CLI entry point
│   ├── config.py                     # Pydantic-settings Config + get_config()
│   │
│   ├── llm/
│   │   ├── base.py                   # LLMProvider ABC
│   │   ├── factory.py                # create_model(config) dispatcher
│   │   ├── openai_provider.py
│   │   ├── anthropic_provider.py
│   │   └── groq_provider.py
│   │
│   └── agent/
│       ├── state.py                  # AgentState TypedDict
│       ├── graph.py                  # StateGraph + conditional edges
│       │
│       ├── nodes/
│       │   ├── parse_script.py
│       │   ├── check_safety.py
│       │   ├── fetch_base_image.py
│       │   ├── generate_dockerfile.py
│       │   ├── execute_dockerfile.py
│       │   ├── validate_output.py
│       │   └── reflect_and_fix.py
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
        ├── Dockerfile.integration
        ├── conftest.py
        ├── test_integration.py
        └── test_scripts/
            ├── word_reverser/
            ├── vowel_counter/
            ├── line_counter/
            ├── matrix_stats/
            ├── malicious/
            ├── prompt_injection/
            └── llm_safety_bypass/
```
