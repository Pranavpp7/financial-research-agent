import { useEffect, useState } from "react";
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

const POSITIVE = "#16a34a"; // green-600
const NEGATIVE = "#dc2626"; // red-600
const NEUTRAL = "#94a3b8"; // slate-400
const NEUTRAL_BAND = 0.05;

export default function SentimentChart() {
  const [data, setData] = useState<SentimentRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSentiments()
      .then((rows) =>
        setData(rows.filter((r) => r.sentiment_score !== null))
      )
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="bg-white rounded-lg shadow p-4 border border-slate-200">
      <h3 className="text-lg font-semibold text-slate-800 mb-3">
        News sentiment by company
      </h3>

      {loading && (
        <p className="text-sm text-slate-500">Loading sentiment...</p>
      )}
      {error && (
        <p className="text-sm text-red-600">
          Could not load sentiment: {error}
        </p>
      )}
      {!loading && !error && data.length === 0 && (
        <p className="text-sm text-slate-500">
          No sentiment scores yet — run{" "}
          <code className="bg-slate-100 px-1 rounded">
            uv run --module backend.ml.sentiment_evaluator
          </code>
          .
        </p>
      )}

      {!loading && data.length > 0 && (
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data}>
            <XAxis dataKey="ticker" tick={{ fontSize: 11 }} />
            <YAxis
              domain={[-1, 1]}
              tickFormatter={(v) => v.toFixed(1)}
              tick={{ fontSize: 11 }}
            />
            <Tooltip
              formatter={(value: number) => [value.toFixed(3), "sentiment"]}
              labelFormatter={(label, payload) => {
                const r = payload?.[0]?.payload as SentimentRow | undefined;
                return r ? `${r.ticker} — ${r.name ?? ""}` : String(label);
              }}
            />
            <ReferenceLine y={0} stroke="#94a3b8" />
            <Bar dataKey="sentiment_score">
              {data.map((row, i) => {
                const score = row.sentiment_score ?? 0;
                const color =
                  Math.abs(score) < NEUTRAL_BAND
                    ? NEUTRAL
                    : score > 0
                    ? POSITIVE
                    : NEGATIVE;
                return <Cell key={i} fill={color} />;
              })}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
