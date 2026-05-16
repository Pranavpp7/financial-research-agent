"""
FastAPI application.

Run:
  uvicorn backend.api.main:app --reload --port 8000

Requires a Celery worker for /analyze to actually process tasks:
  celery -A backend.tasks.celery_app worker --loglevel=info --pool=threads
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import analysis

app = FastAPI(
    title="Financial Research Agent API",
    description=(
        "Multi-source financial analysis: SEC filings (RAG), earnings, news "
        "sentiment, ML risk models, synthesized via Groq Llama 3.3 70B."
    ),
    version="0.1.0",
)

# Dev-friendly CORS. Tighten allow_origins for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        ],
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
