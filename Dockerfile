# Production image for the financial-research-agent backend (API, worker,
# embedder, flower all share this image; the compose `command:` differs).
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    HF_HOME=/models

# Build tools for native wheels (xgboost/torch/psycopg2 deps) + curl for
# healthchecks + WeasyPrint runtime libs (cairo/pango) for PDF export.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential curl git \
        libcairo2 libpango-1.0-0 libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["gunicorn", "backend.api.main:app", "-w", "4", \
     "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", "--error-logfile", "-", "--log-level", "info"]
