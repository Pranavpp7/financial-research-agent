"""
FastAPI application.

Run:
  uvicorn backend.api.main:app --reload --port 8000

Requires a Celery worker for /analyze to actually process tasks:
  celery -A backend.tasks.celery_app worker --loglevel=info --pool=threads
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import analysis
from backend.core.logging import configure_logging
from backend.core.startup import health_snapshot, run_startup_checks

# Configure structured logging before the app handles any request.
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_startup_checks()
    yield


app = FastAPI(
    title="Financial Research Agent API",
    description=(
        "Multi-source financial analysis: SEC filings (RAG), earnings, news "
        "sentiment, ML risk models, synthesized via Groq Llama 3.3 70B."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS. `allow_origins=["*"]` is invalid alongside `allow_credentials=True`
# (browsers reject the wildcard for credentialed requests), so origins are
# an explicit allowlist — configurable via CORS_ORIGINS (comma-separated),
# defaulting to the local Vite/React dev servers.
_cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis.router)


@app.get("/")
def root():
    return {
        "name": "Financial Research Agent API",
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": [
            "GET  /health",
            "POST /analyze",
            "GET  /analyze/{task_id}",
            "GET  /reports/{ticker}",
            "GET  /companies",
            "GET  /stats",
            "GET  /sentiments",
        ],
    }


@app.get("/health")
def health():
    """Dependency health for Docker healthchecks. Never raises."""
    payload, _ok = health_snapshot()
    return payload
