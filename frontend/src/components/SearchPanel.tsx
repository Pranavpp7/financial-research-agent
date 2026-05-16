import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Search, Sparkles } from "lucide-react";

const LOADING_PHASES = [
  "Initializing supervisor...",
  "Running analysis...",
  "Synthesizing report...",
];
const PHASE_INTERVAL_MS = 8_000;
const TYPE_SPEED_MS = 35;

function useTypewriter(text: string, speedMs = TYPE_SPEED_MS) {
  const [out, setOut] = useState("");
  useEffect(() => {
    setOut("");
    if (!text) return;
    let i = 0;
    const id = window.setInterval(() => {
      i += 1;
      setOut(text.slice(0, i));
      if (i >= text.length) window.clearInterval(id);
    }, speedMs);
    return () => window.clearInterval(id);
  }, [text, speedMs]);
  return out;
}

interface Props {
  ticker: string;
  question: string;
  loading: boolean;
  onTickerChange: (t: string) => void;
  onQuestionChange: (q: string) => void;
  onSubmit: () => void;
  error: string | null;
}

export default function SearchPanel({
  ticker,
  question,
  loading,
  onTickerChange,
  onQuestionChange,
  onSubmit,
  error,
}: Props) {
  // Cycle through loading phases.
  const [phaseIdx, setPhaseIdx] = useState(0);
  useEffect(() => {
    if (!loading) {
      setPhaseIdx(0);
      return;
    }
    const id = window.setInterval(() => {
      setPhaseIdx((p) => Math.min(p + 1, LOADING_PHASES.length - 1));
    }, PHASE_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [loading]);

  const typed = useTypewriter(loading ? LOADING_PHASES[phaseIdx] : "");

  return (
    <motion.section
      initial={{ opacity: 0, y: -16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: "easeOut" }}
      className="glass border border-[--color-border-edge] rounded-2xl p-6 shadow-2xl shadow-indigo-500/5"
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!loading) onSubmit();
        }}
        className="flex flex-col gap-4"
      >
        <div className="relative group">
          <Search
            className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-indigo-400 transition-colors"
            size={18}
          />
          <input
            type="text"
            value={ticker}
            onChange={(e) => onTickerChange(e.target.value)}
            placeholder="Enter ticker — AAPL, MSFT, NVDA..."
            disabled={loading}
            className="
              w-full bg-[--color-bg-base]/70 border border-[--color-border-edge]
              rounded-xl pl-12 pr-4 py-4 font-mono text-lg uppercase tracking-wider
              text-slate-100 placeholder:text-slate-600 placeholder:normal-case placeholder:tracking-normal placeholder:font-sans
              focus:outline-none focus:border-indigo-500
              focus:shadow-[0_0_0_4px_rgba(99,102,241,0.15),0_0_20px_rgba(99,102,241,0.25)]
              disabled:opacity-60 transition-all
            "
          />
        </div>

        <input
          type="text"
          value={question}
          onChange={(e) => onQuestionChange(e.target.value)}
          placeholder="Optional question — defaults to a comprehensive analysis"
          disabled={loading}
          className="
            w-full bg-[--color-bg-base]/70 border border-[--color-border-edge]
            rounded-xl px-4 py-3 text-sm text-slate-200 placeholder:text-slate-600
            focus:outline-none focus:border-indigo-500/60
            focus:shadow-[0_0_0_3px_rgba(99,102,241,0.1)]
            disabled:opacity-60 transition-all
          "
        />

        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="text-xs text-slate-500 flex items-center gap-2 min-h-[1.5rem]">
            {loading ? (
              <>
                <Sparkles size={14} className="text-cyan-400 animate-pulse" />
                <span className="text-slate-300 font-mono">
                  {typed}
                  <span className="caret">▍</span>
                </span>
              </>
            ) : (
              <span className="text-slate-600">
                Press analyze to run supervisor → analyzers → synthesizer
              </span>
            )}
          </div>

          <button
            type="submit"
            disabled={loading || !ticker.trim()}
            className="
              relative px-6 py-2.5 rounded-xl font-semibold text-sm
              bg-gradient-to-r from-indigo-500 to-cyan-500
              text-white tracking-wide
              shadow-[0_0_20px_rgba(99,102,241,0.3)]
              hover:shadow-[0_0_30px_rgba(99,102,241,0.5)]
              hover:scale-[1.02]
              disabled:opacity-40 disabled:hover:scale-100 disabled:shadow-none
              transition-all duration-200
            "
          >
            {loading ? "Analyzing..." : "Analyze →"}
          </button>
        </div>

        {error && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-sm text-red-400 border border-red-500/20 bg-red-500/5 rounded-lg px-3 py-2"
          >
            {error}
          </motion.p>
        )}
      </form>
    </motion.section>
  );
}
