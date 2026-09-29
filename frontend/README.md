# Frontend

React dashboard for the Financial Research Agent.

## What it does

Submit a ticker and natural-language question; the UI polls the backend analysis task and shows a synthesized report with bull/bear cases, risk level, confidence score, and source citations. The dashboard also includes a watchlist (with per-ticker alert settings), report history, news sentiment charts, and a separate Backtests view.

## Run locally

The API must already be running (default `http://localhost:8000`).

```bash
npm install
npm run dev
```

Dev server: [http://localhost:5173](http://localhost:5173)

## Config

Copy `.env.example` if you need to override the API origin:

```
VITE_API_BASE_URL=http://localhost:8000
```

When unset, the client defaults to `http://localhost:8000` (see `src/api/client.ts`).
