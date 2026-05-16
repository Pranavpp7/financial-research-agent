import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, Zap } from "lucide-react";
import MetricsGrid from "./components/MetricsGrid";
import ReportCard from "./components/ReportCard";
import SearchPanel from "./components/SearchPanel";
import SentimentChart from "./components/SentimentChart";
import { pollTask, submitAnalysis, type Report } from "./api/client";

const POLL_INTERVAL_MS = 3000;

type Status = "idle" | "submitting" | "running" | "completed" | "failed";

function NavBar() {
  return (
    <motion.nav
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="relative z-10 border-b border-[--color-border-edge] bg-[--color-bg-base]/60 backdrop-blur-md"
    >
      <div className="max-w-[1200px] mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
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
            <span className="text-[10px] uppercase tracking-widest text-slate-500">
              supervisor · analyzers · synthesizer
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span className="relative flex h-2 w-2">
            <span className="absolute inset-0 rounded-full bg-emerald-500 animate-ping opacity-75" />
            <span className="relative rounded-full h-2 w-2 bg-emerald-500" />
          </span>
          <Activity size={12} className="text-emerald-400" />
          <span className="font-mono uppercase tracking-wider">
            System online
          </span>
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
  const pollRef = useRef<number | null>(null);

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
          setStatus("completed");
          setReport(s.result);
        } else if (s.status === "failed") {
          stopPolling();
          setStatus("failed");
          setError(s.error || "task failed");
        }
      } catch (e) {
        stopPolling();
        setStatus("failed");
        setError(String(e));
      }
    }, POLL_INTERVAL_MS);
  };

  const handleSubmit = async () => {
    const t = ticker.trim().toUpperCase();
    if (!t) {
      setError("Please enter a ticker");
      return;
    }
    setError(null);
    setReport(null);
    setStatus("submitting");
    try {
      const r = await submitAnalysis(
        t,
        question.trim() || "Give me a comprehensive analysis"
      );
      setStatus("running");
      startPolling(r.task_id);
    } catch (e) {
      setStatus("failed");
      setError(String(e));
    }
  };

  const loading = status === "submitting" || status === "running";

  return (
    <div className="relative min-h-screen">
      <NavBar />

      <main className="relative z-10 max-w-[1200px] mx-auto px-6 py-10 flex flex-col gap-8">
        <SearchPanel
          ticker={ticker}
          question={question}
          loading={loading}
          onTickerChange={setTicker}
          onQuestionChange={setQuestion}
          onSubmit={handleSubmit}
          error={error}
        />

        <MetricsGrid />

        <SentimentChart />

        <AnimatePresence mode="wait">
          {report && <ReportCard key={report.ticker + report.generated_at} report={report} />}
        </AnimatePresence>
      </main>
    </div>
  );
}
