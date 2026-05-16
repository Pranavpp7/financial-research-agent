import { useEffect, useRef, useState } from "react";
import CompanyList from "./components/CompanyList";
import ReportCard from "./components/ReportCard";
import SentimentChart from "./components/SentimentChart";
import {
  pollTask,
  submitAnalysis,
  type Report,
} from "./api/client";

const POLL_INTERVAL_MS = 3000;

type Status = "idle" | "submitting" | "running" | "completed" | "failed";

export default function App() {
  const [ticker, setTicker] = useState("");
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const pollRef = useRef<number | null>(null);

  // Cleanup interval if the user navigates away mid-task.
  useEffect(() => {
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
      }
    };
  }, []);

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = (taskId: string) => {
    stopPolling();
    pollRef.current = window.setInterval(async () => {
      try {
        const s = await pollTask(taskId);
        if (s.status === "completed") {
          stopPolling();
          setStatus("completed");
          setReport(s.result);
        } else if (s.status === "failed") {
          stopPolling();
          setStatus("failed");
          setError(s.error || "task failed");
        }
        // pending/running -> keep polling
      } catch (e) {
        stopPolling();
        setStatus("failed");
        setError(String(e));
      }
    }, POLL_INTERVAL_MS);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (!t) {
      setError("Please enter a ticker");
      return;
    }
    setError(null);
    setReport(null);
    setStatus("submitting");
    try {
      const result = await submitAnalysis(
        t,
        question.trim() || "Give me a comprehensive analysis"
      );
      setStatus("running");
      startPolling(result.task_id);
    } catch (e) {
      setStatus("failed");
      setError(String(e));
    }
  };

  const isBusy = status === "submitting" || status === "running";

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-6xl mx-auto px-6 py-5">
          <h1 className="text-2xl font-bold text-slate-900">
            Financial Research Agent
          </h1>
          <p className="text-sm text-slate-500">
            Multi-source analysis · earnings · SEC filings · news · ML risk · synthesized by Llama 3.3 70B
          </p>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-6 grid gap-6 grid-cols-1 lg:grid-cols-3">
        <div className="lg:col-span-2 flex flex-col gap-6">
          <form
            onSubmit={handleSubmit}
            className="bg-white rounded-lg shadow p-4 border border-slate-200 flex flex-col gap-3"
          >
            <div className="flex flex-col sm:flex-row gap-3">
              <input
                type="text"
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="Ticker (e.g. AAPL)"
                disabled={isBusy}
                className="font-mono uppercase border border-slate-300 rounded px-3 py-2 text-sm w-full sm:w-44 focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Question (optional)"
                disabled={isBusy}
                className="border border-slate-300 rounded px-3 py-2 text-sm flex-1 focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
              <button
                type="submit"
                disabled={isBusy}
                className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white font-semibold rounded px-5 py-2 text-sm transition"
              >
                {isBusy ? "Analyzing..." : "Analyze"}
              </button>
            </div>
            {status === "running" && (
              <p className="text-xs text-slate-500">
                Task running — polling every 3s. The agent runs supervisor → analyzers → synthesizer.
              </p>
            )}
            {error && (
              <p className="text-sm text-red-600">Error: {error}</p>
            )}
          </form>

          {report ? (
            <ReportCard report={report} />
          ) : isBusy ? (
            <div className="bg-white rounded-lg shadow p-8 border border-slate-200 text-center">
              <div className="inline-block animate-pulse text-slate-400">
                Generating report...
              </div>
            </div>
          ) : (
            <div className="bg-white rounded-lg shadow p-8 border border-slate-200 text-center text-slate-500 text-sm">
              Submit a ticker to generate a research report.
            </div>
          )}

          <SentimentChart />
        </div>

        <aside>
          <CompanyList onSelect={(t) => setTicker(t)} />
        </aside>
      </main>
    </div>
  );
}
