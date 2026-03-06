FROM python:3.12-slim

# Install Docker CLI (needed to build/run generated images)
RUN apt-get update && apt-get install -y --no-install-recommends \
    docker-cli \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml .
COPY dockerfile_gen/ dockerfile_gen/

RUN uv pip install --system --no-cache .

ENTRYPOINT ["python", "-m", "dockerfile_gen.main"]
