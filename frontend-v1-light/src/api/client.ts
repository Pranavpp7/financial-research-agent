import axios from "axios";

export const api = axios.create({
  baseURL: "http://localhost:8000",
  timeout: 60_000,
});

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

export const fetchCompanies = async (): Promise<Company[]> => {
  const r = await api.get<Company[]>("/companies");
  return r.data;
};

export const fetchSentiments = async (): Promise<SentimentRow[]> => {
  const r = await api.get<SentimentRow[]>("/sentiments");
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
