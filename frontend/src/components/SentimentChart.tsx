import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchSentiments, type SentimentRow } from "../api/client";

const COLOR_POS = "#22d3ee"; // cyan-400
const COLOR_NEG = "#ef4444"; // red-500
const COLOR_NEUTRAL = "#64748b"; // slate-500
const NEUTRAL_BAND = 0.05;
const TRIM_THRESHOLD = 20;
const TRIM_EACH_END = 10;

function GlassTooltip({ active, payload }: any) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0].payload as SentimentRow;
  const score = row.sentiment_score ?? 0;
  return (
    <div className="glass border border-border-edge rounded-lg px-3 py-2 shadow-xl">
      <div className="text-xs font-mono text-slate-400">{row.ticker}</div>
      {row.name && <div className="text-sm text-slate-100">{row.name}</div>}
      <div className="text-xs mt-1">
        <span className="text-slate-500">sentiment </span>
        <span
          className={
            Math.abs(score) < NEUTRAL_BAND
              ? "text-slate-400"
              : score > 0
              ? "text-cyan-400 font-semibold"
              : "text-red-400 font-semibold"
          }
        >
          {(score >= 0 ? "+" : "") + score.toFixed(3)}
        </span>
      </div>
    </div>
  );
}

/** Sort high→low; when n > 20 keep top 10 and bottom 10. */
function selectChartRows(rows: SentimentRow[]): {
  chart: SentimentRow[];
  total: number;
  trimmed: boolean;
} {
  const sorted = [...rows].sort(
    (a, b) => (b.sentiment_score ?? 0) - (a.sentiment_score ?? 0)
  );
  if (sorted.length <= TRIM_THRESHOLD) {
    return { chart: sorted, total: sorted.length, trimmed: false };
  }
  const top = sorted.slice(0, TRIM_EACH_END);
  const bottom = sorted.slice(-TRIM_EACH_END);
  // Preserve high→low overall: top block then bottom block.
  return {
    chart: [...top, ...bottom],
    total: sorted.length,
    trimmed: true,
  };
}

export default function SentimentChart() {
  const [data, setData] = useState<SentimentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSentiments()
      .then((rows) => setData(rows.filter((r) => r.sentiment_score !== null)))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const { chart, total, trimmed } = useMemo(
    () => selectChartRows(data),
    [data]
  );

  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.1, ease: "easeOut" }}
      className="glass border border-border-edge rounded-2xl p-5"
    >
      <div className="flex items-baseline justify-between mb-4 gap-3 flex-wrap">
        <h3 className="text-sm uppercase tracking-widest text-slate-500">
          News sentiment by company
        </h3>
        <span className="text-[11px] text-slate-600 font-mono">
          finbert · range [-1, +1]
        </span>
      </div>

      {loading && (
        <p className="text-sm text-slate-500">Loading sentiment...</p>
      )}
      {error && (
        <p className="text-sm text-red-400">Could not load sentiment: {error}</p>
      )}
      {!loading && !error && data.length === 0 && (
        <p className="text-sm text-slate-500">
          No sentiment scores yet — run{" "}
          <code className="px-1.5 py-0.5 rounded bg-bg-base border border-border-edge text-slate-400 text-[11px]">
            uv run --module backend.ml.sentiment_evaluator
          </code>
        </p>
      )}

      {!loading && chart.length > 0 && (
        <>
          {trimmed && (
            <p className="text-[11px] text-slate-500 mb-3">
              Top {TRIM_EACH_END} and bottom {TRIM_EACH_END} of {total} companies
            </p>
          )}
          <ResponsiveContainer width="100%" height={300}>
            <BarChart
              data={chart}
              margin={{ top: 10, right: 12, bottom: 28, left: -10 }}
            >
              <XAxis
                dataKey="ticker"
                interval={0}
                angle={-35}
                textAnchor="end"
                height={50}
                tick={{ fontSize: 10, fill: "#64748b", fontFamily: "monospace" }}
                tickLine={{ stroke: "#1e1e2e" }}
                axisLine={{ stroke: "#1e1e2e" }}
              />
              <YAxis
                domain={[-1, 1]}
                tickFormatter={(v) => v.toFixed(1)}
                tick={{ fontSize: 11, fill: "#64748b" }}
                tickLine={{ stroke: "#1e1e2e" }}
                axisLine={{ stroke: "#1e1e2e" }}
              />
              <Tooltip
                content={<GlassTooltip />}
                cursor={{ fill: "rgba(99,102,241,0.06)" }}
              />
              <ReferenceLine y={0} stroke="#1e1e2e" strokeWidth={1} />
              <Bar
                dataKey="sentiment_score"
                radius={[4, 4, 0, 0]}
                animationDuration={900}
                animationEasing="ease-out"
              >
                {chart.map((row, i) => {
                  const score = row.sentiment_score ?? 0;
                  const color =
                    Math.abs(score) < NEUTRAL_BAND
                      ? COLOR_NEUTRAL
                      : score > 0
                      ? COLOR_POS
                      : COLOR_NEG;
                  return <Cell key={`${row.ticker}-${i}`} fill={color} />;
                })}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </>
      )}
    </motion.section>
  );
}
