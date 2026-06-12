import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronDown } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  createBacktest,
  getBacktest,
  getBacktestResults,
  listBacktests,
  type BacktestResultRow,
} from "../api/client";

const LIMITATIONS = [
  "Reports cluster around batch-ingestion runs, not uniform intervals — this biases the sample.",
  "No lookahead-bias guard: assumes each report only used data up to its date.",
  "'Signal' is a coarse heuristic, not a real trading strategy.",
  "Forward returns are gross — no transaction costs, slippage, or borrow costs.",
  "Per-ticker sample sizes are usually small (<10). Results are illustrative, not significant.",
];

const SIGNAL_COLOR: Record<string, string> = {
  bullish: "#10b981",
  bearish: "#ef4444",
  neutral: "#64748b",
};

function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;
}

export default function BacktestView() {
  const [name, setName] = useState("");
  const [minConfidence, setMinConfidence] = useState(0);
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<number | null>(null);
  const [run, setRun] = useState<Record<string, unknown> | null>(null);
  const [results, setResults] = useState<BacktestResultRow[]>([]);
  const [showLimits, setShowLimits] = useState(false);
  const pollRef = useRef<number | null>(null);

  useEffect(() => () => stopPoll(), []);

  const stopPoll = () => {
    if (pollRef.current !== null) window.clearInterval(pollRef.current);
    pollRef.current = null;
  };

  const submit = async () => {
    setRunning(true);
    setRun(null);
    setResults([]);
    await createBacktest({
      name: name.trim() || `Backtest ${new Date().toISOString()}`,
      min_confidence: minConfidence,
    });
    // Poll the run list for the newest run and watch it complete.
    stopPoll();
    pollRef.current = window.setInterval(async () => {
      const runs = await listBacktests();
      if (runs.length === 0) return;
      const newest = runs[0];
      setRunId(newest.id);
      if (newest.status === "completed" || newest.status === "failed") {
        stopPoll();
        setRunning(false);
        setRun(await getBacktest(newest.id));
        setResults(await getBacktestResults(newest.id));
      }
    }, 3000);
  };

  const summary = (run?.summary as Record<string, number | null> | undefined) ?? undefined;
  const byTicker = (summary?.by_ticker as unknown as Record<string, { n: number; hit_rate_30d: number | null }>) ?? {};
  const tickerBars = Object.entries(byTicker).map(([ticker, v]) => ({
    ticker,
    hit_rate: v.hit_rate_30d ?? 0,
  }));
  const scatterData = results
    .filter((r) => r.confidence_score !== null && r.return_30d !== null)
    .map((r) => ({
      x: r.confidence_score,
      y: (r.return_30d ?? 0) * 100,
      signal: r.signal,
      ticker: r.ticker,
      date: r.report_date,
    }));

  return (
    <div className="flex flex-col gap-6">
      {/* Methodology banner */}
      <div className="glass border border-amber-500/30 rounded-2xl p-4">
        <button
          onClick={() => setShowLimits((s) => !s)}
          className="flex items-center gap-2 text-sm text-amber-300 w-full"
        >
          <AlertTriangle size={16} />
          Backtest results are illustrative only. See methodology limitations.
          <ChevronDown size={15} className={`ml-auto transition-transform ${showLimits ? "rotate-180" : ""}`} />
        </button>
        {showLimits && (
          <ul className="mt-3 list-disc pl-6 text-xs text-amber-100/80 space-y-1">
            {LIMITATIONS.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        )}
      </div>

      {/* Form */}
      <div className="glass border border-[--color-border-edge] rounded-2xl p-6 flex flex-col gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">Run a backtest</h2>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Backtest name"
          className="bg-[--color-bg-base]/70 border border-[--color-border-edge] rounded-lg px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600"
        />
        <label className="text-xs text-slate-400">
          Min confidence: {minConfidence.toFixed(2)}
          <input
            type="range" min={0} max={1} step={0.05}
            value={minConfidence}
            onChange={(e) => setMinConfidence(parseFloat(e.target.value))}
            className="w-full mt-1"
          />
        </label>
        <button
          onClick={submit}
          disabled={running}
          className="self-start rounded-lg bg-gradient-to-r from-indigo-500 to-cyan-500 px-5 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          {running ? "Running..." : "Run Backtest"}
        </button>
        {running && (
          <p className="text-xs text-slate-500">
            Running{runId ? ` (run #${runId})` : ""}... fetching prices via yfinance, this can take a while.
          </p>
        )}
      </div>

      {/* Results */}
      {summary && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              ["Total reports", summary.total_reports ?? 0],
              ["Bullish hit 30d", pct(summary.bullish_hit_rate_30d)],
              ["Bearish hit 30d", pct(summary.bearish_hit_rate_30d)],
              ["Avg bull 30d", pct(summary.avg_return_bullish_30d)],
            ].map(([label, val]) => (
              <div key={label as string} className="glass border border-[--color-border-edge] rounded-xl p-4">
                <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
                <div className="text-xl font-bold text-slate-100">{val}</div>
              </div>
            ))}
          </div>

          <div className="glass border border-[--color-border-edge] rounded-2xl p-4">
            <h3 className="text-xs uppercase tracking-wider text-slate-400 mb-3">Hit rate by ticker (30d)</h3>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={tickerBars}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
                <XAxis dataKey="ticker" stroke="#64748b" fontSize={11} />
                <YAxis domain={[0, 1]} stroke="#64748b" fontSize={11} />
                <Tooltip contentStyle={{ background: "#111118", border: "1px solid #1e1e2e" }} />
                <Bar dataKey="hit_rate" fill="#6366f1" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="glass border border-[--color-border-edge] rounded-2xl p-4">
            <h3 className="text-xs uppercase tracking-wider text-slate-400 mb-3">Confidence vs 30d return (%)</h3>
            <ResponsiveContainer width="100%" height={260}>
              <ScatterChart>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
                <XAxis type="number" dataKey="x" name="confidence" domain={[0, 1]} stroke="#64748b" fontSize={11} />
                <YAxis type="number" dataKey="y" name="return30d" stroke="#64748b" fontSize={11} />
                <Tooltip
                  contentStyle={{ background: "#111118", border: "1px solid #1e1e2e" }}
                />
                <Scatter data={scatterData}>
                  {scatterData.map((d, i) => (
                    <Cell key={i} fill={SIGNAL_COLOR[d.signal] ?? "#64748b"} />
                  ))}
                </Scatter>
              </ScatterChart>
            </ResponsiveContainer>
          </div>

          <div className="glass border border-[--color-border-edge] rounded-2xl p-4 overflow-x-auto">
            <h3 className="text-xs uppercase tracking-wider text-slate-400 mb-3">Per-report results</h3>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-slate-500 text-left">
                  <th className="py-1 pr-3">Ticker</th>
                  <th className="py-1 pr-3">Date</th>
                  <th className="py-1 pr-3">Signal</th>
                  <th className="py-1 pr-3">Conf</th>
                  <th className="py-1 pr-3">30d</th>
                  <th className="py-1 pr-3">90d</th>
                  <th className="py-1 pr-3">Hit</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={i} className="border-t border-[--color-border-edge] text-slate-300">
                    <td className="py-1 pr-3 font-mono">{r.ticker}</td>
                    <td className="py-1 pr-3">{r.report_date?.slice(0, 10)}</td>
                    <td className="py-1 pr-3" style={{ color: SIGNAL_COLOR[r.signal] }}>{r.signal}</td>
                    <td className="py-1 pr-3">{pct(r.confidence_score)}</td>
                    <td className="py-1 pr-3">{pct(r.return_30d)}</td>
                    <td className="py-1 pr-3">{pct(r.return_90d)}</td>
                    <td className="py-1 pr-3">{r.hit === null ? "—" : r.hit ? "✓" : "✗"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
