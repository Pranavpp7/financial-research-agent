import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, Menu, Zap } from "lucide-react";
import BacktestView from "./components/BacktestView";
import MetricsGrid from "./components/MetricsGrid";
import ReportCard from "./components/ReportCard";
import ReportHistory from "./components/ReportHistory";
import SearchPanel from "./components/SearchPanel";
import SentimentChart from "./components/SentimentChart";
import Watchlist from "./components/Watchlist";
import { pollTask, submitAnalysis, type Report } from "./api/client";
import { formatAnalysisError } from "./lib/formatAnalysisError";

const POLL_INTERVAL_MS = 3000;
const SIDEBAR_KEY = "watchlist_open";

type Status = "idle" | "submitting" | "running" | "completed" | "failed";

interface RateLimit {
  service: string;
  retryAfter: number;
}

type View = "dashboard" | "backtests";

function NavBar({
  onToggleSidebar,
  view,
  onSetView,
}: {
  onToggleSidebar: () => void;
  view: View;
  onSetView: (v: View) => void;
}) {
  return (
    <motion.nav
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="relative z-10 border-b border-border-edge bg-bg-base/60 backdrop-blur-md"
    >
      <div className="max-w-[1400px] mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={onToggleSidebar}
            className="md:hidden text-slate-400 hover:text-slate-100"
            aria-label="toggle watchlist"
          >
            <Menu size={20} />
          </button>
          <div className="relative">
            <div className="absolute inset-0 bg-gradient-to-br from-indigo-500 to-cyan-400 blur-md opacity-50" />
            <div className="relative w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-cyan-400 flex items-center justify-center">
              <Zap size={16} className="text-white" />
            </div>
          </div>
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-semibold tracking-wide text-slate-100">
              Financial Research Agent
            </span>
            <span className="text-[10px] uppercase tracking-wider text-slate-500 hidden sm:block truncate max-w-[min(28rem,calc(100vw-16rem))]">
              AI equity research from SEC filings, earnings and news
            </span>
          </div>
        </div>

        <div className="flex items-center gap-5">
          <div className="flex items-center gap-3 text-xs">
            <button
              onClick={() => onSetView("dashboard")}
              className={view === "dashboard" ? "text-slate-100 font-semibold" : "text-slate-500 hover:text-slate-300"}
            >
              Dashboard
            </button>
            <button
              onClick={() => onSetView("backtests")}
              className={view === "backtests" ? "text-slate-100 font-semibold" : "text-slate-500 hover:text-slate-300"}
            >
              Backtests
            </button>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span className="relative flex h-2 w-2">
              <span className="absolute inset-0 rounded-full bg-emerald-500 animate-ping opacity-75" />
              <span className="relative rounded-full h-2 w-2 bg-emerald-500" />
            </span>
            <Activity size={12} className="text-emerald-400" />
            <span className="font-mono uppercase tracking-wider">System online</span>
          </div>
        </div>
      </div>
    </motion.nav>
  );
}

export default function App() {
  const [ticker, setTicker] = useState("");
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [progress, setProgress] = useState<{ pct: number; message: string } | null>(null);
  const [rateLimit, setRateLimit] = useState<RateLimit | null>(null);
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => {
    const v = localStorage.getItem(SIDEBAR_KEY);
    return v === null ? true : v === "true";
  });
  const [view, setView] = useState<View>("dashboard");
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    localStorage.setItem(SIDEBAR_KEY, String(sidebarOpen));
  }, [sidebarOpen]);

  useEffect(() => {
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
          setProgress(null);
          setStatus("completed");
          setReport(s.result);
          setRefreshKey((k) => k + 1); // refresh watchlist + history
        } else if (s.status === "failed") {
          stopPolling();
          setProgress(null);
          setStatus("failed");
          if (s.error === "rate_limit_exceeded") {
            setRateLimit({
              service: s.service || "groq",
              retryAfter: s.retry_after_seconds || 30,
            });
            setError(null);
          } else {
            setError(formatAnalysisError(s.error || "task failed"));
          }
        } else if (s.status === "progress") {
          setProgress({ pct: s.pct ?? 0, message: s.message || "Working..." });
        }
      } catch (e) {
        stopPolling();
        setStatus("failed");
        // Prefer the API's error detail (e.g. "unknown or expired task id")
        // over the raw "AxiosError: Request failed with status code 404".
        const detail = (e as { response?: { data?: { detail?: string } } })
          ?.response?.data?.detail;
        setError(formatAnalysisError(detail ?? String(e)));
      }
    }, POLL_INTERVAL_MS);
  };

  const runAnalysis = async (rawTicker: string, q: string, forceRefresh = false) => {
    const t = rawTicker.trim().toUpperCase();
    if (!t) {
      setError("Please enter a ticker");
      return;
    }
    setError(null);
    setReport(null);
    setProgress(null);
    setRateLimit(null);
    setStatus("submitting");
    setSelectedTicker(t);
    try {
      const r = await submitAnalysis(
        t,
        q.trim() || "Give me a comprehensive analysis",
        forceRefresh
      );
      setStatus("running");
      startPolling(r.task_id);
    } catch (e) {
      setStatus("failed");
      setError(formatAnalysisError(String(e)));
    }
  };

  const handleSubmit = () => runAnalysis(ticker, question);

  const handleWatchlistAnalyze = (t: string) => {
    setTicker(t);
    runAnalysis(t, question);
  };

  const loading = status === "submitting" || status === "running";

  return (
    <div className="relative min-h-screen">
      <NavBar onToggleSidebar={() => setSidebarOpen((o) => !o)} view={view} onSetView={setView} />

      <div className="relative z-10 max-w-[1400px] mx-auto px-6 py-8 flex gap-6">
        {/* Sidebar / drawer */}
        <AnimatePresence>
          {sidebarOpen && (
            <motion.aside
              initial={{ opacity: 0, x: -16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -16 }}
              className="
                w-64 shrink-0 glass border border-border-edge rounded-2xl p-4
                md:static fixed inset-y-0 left-0 z-20 md:z-auto overflow-y-auto
              "
            >
              <Watchlist refreshKey={refreshKey} onAnalyze={handleWatchlistAnalyze} />
            </motion.aside>
          )}
        </AnimatePresence>

        {/* Main column */}
        <main className="flex-1 min-w-0 flex flex-col gap-8">
          {view === "backtests" ? (
            <BacktestView />
          ) : (
          <>
          <SearchPanel
            ticker={ticker}
            question={question}
            loading={loading}
            progress={progress}
            rateLimit={rateLimit}
            onTickerChange={setTicker}
            onQuestionChange={setQuestion}
            onSubmit={handleSubmit}
            error={error}
          />

          <MetricsGrid />

          <SentimentChart />

          <AnimatePresence mode="wait">
            {report && (
              <div key={report.ticker + report.generated_at} className="flex flex-col gap-3">
                <ReportCard
                  report={report}
                  onRefresh={() =>
                    runAnalysis(report.ticker, question || "Give me a comprehensive analysis", true)
                  }
                />
              </div>
            )}
          </AnimatePresence>

          <ReportHistory
            ticker={selectedTicker}
            refreshKey={refreshKey}
            onSelect={setReport}
          />
          </>
          )}
        </main>
      </div>
    </div>
  );
}
