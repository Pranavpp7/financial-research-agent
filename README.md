# Financial Research Platform

Ask a natural-language question about a public company and get a structured,
source-cited research report. The system routes the question to the right mix
of specialist analyses — SEC-filing semantic search, earnings-surprise
prediction, news sentiment, accounting-risk models, and revenue forecasting —
then synthesizes bull/bear cases, risk level, and confidence.

Built as a portfolio project to demonstrate a production-shaped system:
multi-source ingestion, a vector RAG pipeline, six ML models with
explainability, an async task queue, and a React dashboard — all containerized.

> For research and educational use only. Nothing here is financial advice.

---

## Architecture

```
                    ┌─────────────┐
   question +       │  Supervisor │   one Groq/Llama-3.3-70B call in JSON mode
   ticker  ───────► │  (router)   │   picks the minimal set of analyses
                    └──────┬──────┘
                           │  ["earnings", "sec", "news", "risk", "forecast"]
                           ▼
                    ┌─────────────┐   loads data per analysis type from Postgres
                    │  Analyzer   │   (+ pgvector RAG for "sec"), prompts the LLM
                    └──────┬──────┘   once per selected analysis
                           │  specialist analyses
                           ▼
                    ┌─────────────┐   merges analyses into a single JSON report
                    │ Synthesizer │   and persists report + citations
                    └──────┬──────┘
                           ▼
              reports + report_citations  ──►  FastAPI  ──►  React dashboard
```

One LLM is used as several personas: the supervisor produces a route, the
analyzer runs each selected persona against the relevant data, and the
synthesizer combines the outputs. Long-running analysis is dispatched to
**Celery** so the API stays responsive.

### Data & ML

| Component | What it does | Tech |
|---|---|---|
| Ingestion | SEC EDGAR filings, yfinance earnings, NewsAPI articles | `requests`, `yfinance`, `beautifulsoup4` |
| RAG | 10-K/10-Q chunked, embedded, semantic search | `pgvector`, `bge-large-en-v1.5` |
| Earnings surprise | Predicts next-quarter EPS beat (no temporal leakage) | XGBoost + SHAP |
| News sentiment | Per-article + aggregate sentiment | FinBERT |
| Accounting risk | Beneish M-Score + Isolation-Forest anomaly detector | scikit-learn |
| Revenue forecast | Next-quarter revenue + trend/seasonality | Prophet |
| Peer clustering | Competitive-set grouping | KMeans |
| Experiment tracking | Params, metrics, SHAP plots, model artifacts | MLflow |
| RAG evaluation | Faithfulness / relevancy / context precision | Ragas |

Every ML prediction is persisted to `ml_predictions` with its SHAP values and
input features, so the report layer can explain *why* — and surfaces
cold-start / insufficient-data sentinels instead of silently skipping a
company.

---

## Tech stack

**Backend** Python 3.13 · FastAPI · SQLAlchemy 2 · PostgreSQL + pgvector ·
Redis · Celery · Groq (Llama 3.3 70B) · XGBoost · Prophet · scikit-learn ·
SHAP · sentence-transformers · MLflow · Ragas

**Frontend** React 19 · TypeScript · Vite · Tailwind · Recharts · Framer Motion

**Infra** Docker / docker-compose · Gunicorn + Uvicorn workers · Alembic
migrations

---

## Getting started

### Prerequisites
- [uv](https://astral.sh/uv/) (Python package manager)
- Docker (for Postgres + Redis), or local Postgres 16 with the `pgvector`
  extension and a Redis server
- API keys: [Groq](https://console.groq.com), [NewsAPI](https://newsapi.org)

### 1. Configure environment
```bash
cp .env.example .env   # then fill in your keys and DB/Redis settings
```

Host-side `uv` against Docker Compose Postgres should use port **5455**
(see `.env.example`). Inside containers, Postgres listens on 5432.

### 2. Start infrastructure
```bash
docker compose up -d postgres redis
```

### 3. Install dependencies & run migrations
```bash
uv sync
uv run alembic upgrade head
```

### 4. Run the stack
```bash
# API
uv run uvicorn backend.api.main:app --reload --port 8000

# Celery worker (separate terminal) — required for /analyze to process
uv run celery -A backend.tasks.celery_app worker --loglevel=info --pool=threads

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

API docs: http://localhost:8000/docs · Frontend: http://localhost:5173

### Train the ML models
Models read from Postgres and write predictions back to `ml_predictions`.
Run a module from the project root, e.g.:
```bash
uv run --module backend.ml.earnings_predictor
```

---

## Testing

```bash
uv run pytest
```

The suite covers the deterministic core: earnings feature engineering
(no-leakage contract, cold-start/partial-data sentinels, time-based split),
the Beneish M-Score math and thresholds, ingestion utilities, and LLM-output
sanitization.

---

## Key API endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/analyze` | Kick off analysis for a ticker + question (async) |
| `GET` | `/analyze/{task_id}` | Poll task status / result |
| `GET` | `/reports/{ticker}` | Report history for a ticker |
| `GET` | `/companies` · `/stats` · `/sentiments` | Dashboard data |
| `GET` | `/health` | Ops / dependency health |

---

## Project layout

```
backend/
  ml/            earnings, anomaly, beneish, sentiment, peer clustering, forecaster
  rag/           chunking, embedding, retrieval, QA
  ingestion/     EDGAR / yfinance / NewsAPI clients + pipeline
  api/           FastAPI app, routes, schemas
  tasks/         Celery app and analysis task
  core/          logging, startup checks, Groq retry helper
  db/            SQLAlchemy models, CRUD, Alembic migrations
  (plus supervisor / analyzer / synthesizer / prompts packages)
frontend/        React + Vite dashboard
tests/           pytest suite
```
