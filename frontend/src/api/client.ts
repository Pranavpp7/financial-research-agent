import axios from "axios";

export const api = axios.create({
  baseURL: "http://localhost:8000",
  timeout: 60_000,
});

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

export interface Report {
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
}

export interface TaskSubmit {
  task_id: string;
  status: string;
  message: string;
}

export interface TaskStatus {
  task_id: string;
  status: "pending" | "running" | "completed" | "failed";
  result: Report | null;
  error: string | null;
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
  question: string
): Promise<TaskSubmit> => {
  const r = await api.post<TaskSubmit>("/analyze", { ticker, question });
  return r.data;
};

export const pollTask = async (taskId: string): Promise<TaskStatus> => {
  const r = await api.get<TaskStatus>(`/analyze/${taskId}`);
  return r.data;
};
