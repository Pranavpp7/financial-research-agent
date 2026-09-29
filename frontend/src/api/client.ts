import axios from "axios";

export const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 60_000,
});

/**
 * Parse a backend timestamp as UTC. The API stores naive-UTC datetimes and
 * serializes them without a timezone designator (e.g. "2026-06-11T02:00:00"),
 * which `new Date()` would otherwise interpret as LOCAL time — shifting every
 * displayed date by the viewer's UTC offset.
 */
export function parseUtc(iso: string): Date {
  const hasZone = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasZone ? iso : `${iso}Z`);
}

// Dev-only request logging.
if (import.meta.env.DEV) {
  api.interceptors.request.use((config) => {
    // eslint-disable-next-line no-console
    console.debug(
      `[api] ${config.method?.toUpperCase()} ${config.baseURL}${config.url}`,
      config.data ?? ""
    );
    return config;
  });
  api.interceptors.response.use(
    (res) => {
      // eslint-disable-next-line no-console
      console.debug(`[api] ${res.status} ${res.config.url}`, res.data);
      return res;
    },
    (err) => {
      // eslint-disable-next-line no-console
      console.warn(`[api] error ${err.config?.url}`, err.message);
      return Promise.reject(err);
    }
  );
}

export interface Company {
  ticker: string;
  name: string | null;
  sector: string | null;
  industry: string | null;
}

export interface ForecastSignal {
  forecast_next_q?: number;
  forecast_2q?: number;
  forecast_low?: number;
  forecast_high?: number;
  trend_direction?: "up" | "flat" | "down";
  seasonality_strength?: number;
  periods_used?: number;
  // cold-start sentinel
  status?: string;
  quarters_available?: number;
  quarters_required?: number;
}

export interface PeerSignal {
  cluster_id?: number;
  cluster_size?: number;
  peer_tickers?: string[];
  cluster_label?: string;
  silhouette?: number;
}

export interface MlSignals {
  anomaly?: { flagged?: boolean; score?: number | null; label?: string | null } | null;
  beneish?: { label?: string | null; score?: number | null } | null;
  earnings?: { beat?: boolean | null; confidence?: number | null; label?: string | null } | null;
  sentiment?: { score?: number | null; label?: string | null } | null;
}

export interface Report {
  report_id?: number | null;
  ticker: string;
  company_name: string | null;
  generated_at: string | null;
  bull_case: string | null;
  bear_case: string | null;
  risk_level: "low" | "medium" | "high" | null;
  confidence_score: number | null;
  data_quality: number | null;
  analyst_notes: string | null;
  key_findings: string[] | null;
  sources: unknown[] | null;
  forecast: ForecastSignal | null;
  peers: PeerSignal | null;
  ml_signals?: MlSignals | null;
  from_cache?: boolean | null;
  age_minutes?: number | null;
}

export interface TaskSubmit {
  task_id: string;
  status: string;
  message: string;
}

export interface TaskStatus {
  task_id: string;
  status: "pending" | "running" | "progress" | "completed" | "failed";
  result: Report | null;
  error: string | null;
  stage?: string | null;
  message?: string | null;
  pct?: number | null;
  service?: string | null;
  retry_after_seconds?: number | null;
}

export interface SentimentRow {
  ticker: string;
  name: string | null;
  sentiment_score: number | null;
  label: string | null;
}

export interface Stats {
  total_companies: number;
  average_sentiment: number | null;
  reports_today: number;
  models_running: number;
}

export const fetchCompanies = async (): Promise<Company[]> => {
  const r = await api.get<Company[]>("/companies");
  return r.data;
};

export const fetchSentiments = async (): Promise<SentimentRow[]> => {
  const r = await api.get<SentimentRow[]>("/sentiments");
  return r.data;
};

export const fetchStats = async (): Promise<Stats> => {
  const r = await api.get<Stats>("/stats");
  return r.data;
};

export const submitAnalysis = async (
  ticker: string,
  question: string,
  forceRefresh = false
): Promise<TaskSubmit> => {
  const r = await api.post<TaskSubmit>("/analyze", {
    ticker,
    question,
    force_refresh: forceRefresh,
  });
  return r.data;
};

export const pollTask = async (taskId: string): Promise<TaskStatus> => {
  const r = await api.get<TaskStatus>(`/analyze/${taskId}`);
  return r.data;
};

// ── Watchlist + history ────────────────────────────────────────────
export interface WatchlistItem {
  ticker: string;
  notes: string | null;
  created_at: string | null;
}

export interface WatchlistSummaryItem {
  ticker: string;
  notes: string | null;
  risk_level: "low" | "medium" | "high" | null;
  confidence_score: number | null;
  last_analyzed: string | null;
}

export interface ReportHistoryItem {
  report_id: number;
  created_at: string | null;
  risk_level: "low" | "medium" | "high" | null;
  confidence_score: number | null;
  bull_case: string | null;
  bear_case: string | null;
  key_findings: string[] | null;
  data_quality: number | null;
  analyst_notes: string | null;
}

export const getWatchlist = async (): Promise<WatchlistItem[]> => {
  const r = await api.get<WatchlistItem[]>("/watchlist");
  return r.data;
};

export const addToWatchlist = async (
  ticker: string,
  notes?: string
): Promise<WatchlistItem> => {
  const r = await api.post<WatchlistItem>("/watchlist", { ticker, notes });
  return r.data;
};

export const removeFromWatchlist = async (ticker: string): Promise<void> => {
  await api.delete(`/watchlist/${ticker}`);
};

export const getWatchlistSummary = async (): Promise<WatchlistSummaryItem[]> => {
  const r = await api.get<WatchlistSummaryItem[]>("/watchlist/summary");
  return r.data;
};

export const getReportHistory = async (
  ticker: string
): Promise<ReportHistoryItem[]> => {
  const r = await api.get<ReportHistoryItem[]>(`/reports/${ticker}`);
  return r.data;
};

export interface ScheduleStatus {
  beat_running: boolean;
  next_runs: Record<string, string>;
  last_runs: Record<string, unknown>;
}

export const getScheduleStatus = async (): Promise<ScheduleStatus> => {
  const r = await api.get<ScheduleStatus>("/schedule/status");
  return r.data;
};

// ── Alerts ──────────────────────────────────────────────────────────
export interface AlertSubscription {
  id: number;
  ticker: string;
  channel: "email" | "slack";
  destination: string;
  triggers: string[];
  last_fired_at: string | null;
}

export interface AlertHistoryItem {
  id: number;
  subscription_id: number;
  fired_at: string | null;
  trigger_type: string | null;
  report_id_before: number | null;
  report_id_after: number | null;
  delivery_status: string | null;
  delivery_error: string | null;
}

export const subscribeAlert = async (body: {
  ticker: string;
  channel: "email" | "slack";
  destination: string;
  triggers: string[];
}): Promise<{ subscription_id: number }> => {
  const r = await api.post("/alerts/subscribe", body);
  return r.data;
};

export const listAlertSubscriptions = async (
  ticker: string
): Promise<AlertSubscription[]> => {
  const r = await api.get<AlertSubscription[]>("/alerts/subscriptions", {
    params: { ticker },
  });
  return r.data;
};

export const deleteAlertSubscription = async (id: number): Promise<void> => {
  await api.delete(`/alerts/subscriptions/${id}`);
};

export const getAlertHistory = async (
  ticker: string,
  limit = 50
): Promise<AlertHistoryItem[]> => {
  const r = await api.get<AlertHistoryItem[]>("/alerts/history", {
    params: { ticker, limit },
  });
  return r.data;
};

export const testAlert = async (
  id: number
): Promise<{ sent: boolean; error: string | null }> => {
  const r = await api.post(`/alerts/test/${id}`);
  return r.data;
};

// ── Backtesting ─────────────────────────────────────────────────────
export interface BacktestRunBrief {
  id: number;
  name: string;
  created_at: string | null;
  status: string;
  summary_brief: {
    total_reports?: number | null;
    bullish_hit_rate_30d?: number | null;
    bearish_hit_rate_30d?: number | null;
  };
}

export interface BacktestResultRow {
  report_id: number;
  ticker: string;
  report_date: string | null;
  signal: "bullish" | "bearish" | "neutral";
  confidence_score: number | null;
  risk_level: string | null;
  entry_price: number | null;
  return_30d: number | null;
  return_90d: number | null;
  hit: number | null;
}

export const createBacktest = async (body: {
  name: string;
  tickers?: string[] | null;
  min_confidence?: number;
}): Promise<{ task_id: string; status: string }> => {
  const r = await api.post("/backtest", body);
  return r.data;
};

export const listBacktests = async (): Promise<BacktestRunBrief[]> => {
  const r = await api.get<BacktestRunBrief[]>("/backtest");
  return r.data;
};

export const getBacktest = async (
  runId: number
): Promise<Record<string, unknown>> => {
  const r = await api.get(`/backtest/${runId}`);
  return r.data;
};

export const getBacktestResults = async (
  runId: number,
  limit = 200
): Promise<BacktestResultRow[]> => {
  const r = await api.get<BacktestResultRow[]>(`/backtest/${runId}/results`, {
    params: { limit },
  });
  return r.data;
};
