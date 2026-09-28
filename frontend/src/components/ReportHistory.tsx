import { useEffect, useState } from "react";
import { format } from "date-fns";
import { getReportHistory, parseUtc, type Report, type ReportHistoryItem } from "../api/client";

const RISK_PILL: Record<string, string> = {
  low: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  medium: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  high: "bg-red-500/15 text-red-300 border-red-500/30",
};

function toReport(item: ReportHistoryItem, ticker: string): Report {
  return {
    report_id: item.report_id,
    ticker,
    company_name: ticker,
    generated_at: item.created_at,
    bull_case: item.bull_case,
    bear_case: item.bear_case,
    risk_level: item.risk_level,
    confidence_score: item.confidence_score,
    data_quality: item.data_quality,
    analyst_notes: item.analyst_notes,
    key_findings: item.key_findings,
    sources: null,
    forecast: null,
    peers: null,
  };
}

interface Props {
  ticker: string | null;
  refreshKey: number;
  onSelect: (report: Report) => void;
}

export default function ReportHistory({ ticker, refreshKey, onSelect }: Props) {
  const [items, setItems] = useState<ReportHistoryItem[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [compare, setCompare] = useState<number[]>([]);

  useEffect(() => {
    if (!ticker) {
      setItems([]);
      return;
    }
    getReportHistory(ticker)
      .then(setItems)
      .catch(() => setItems([]));
    setCompare([]);
  }, [ticker, refreshKey]);

  if (!ticker) return null;

  if (items.length === 0) {
    return (
      <div className="glass border border-[--color-border-edge] rounded-2xl p-6 text-sm text-slate-500">
        No previous reports for {ticker}. Run an analysis to get started.
      </div>
    );
  }

  const toggleCompare = (id: number) =>
    setCompare((prev) =>
      prev.includes(id)
        ? prev.filter((x) => x !== id)
        : prev.length >= 2
          ? [prev[1], id]
          : [...prev, id]
    );

  const compared = compare
    .map((id) => items.find((i) => i.report_id === id))
    .filter((x): x is ReportHistoryItem => Boolean(x));

  return (
    <div className="glass border border-[--color-border-edge] rounded-2xl p-6">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300 mb-4">
        Report history — {ticker}
      </h3>

      <div className="relative border-l border-[--color-border-edge] pl-4 flex flex-col gap-3">
        {items.map((it) => {
          const pill = it.risk_level
            ? RISK_PILL[it.risk_level]
            : "bg-slate-500/15 text-slate-400 border-slate-500/30";
          const isOpen = expanded === it.report_id;
          const inCompare = compare.includes(it.report_id);
          return (
            <div
              key={it.report_id}
              className="relative rounded-lg border border-[--color-border-edge] bg-[--color-bg-base]/40 p-3"
            >
              <span className="absolute -left-[22px] top-4 h-2 w-2 rounded-full bg-indigo-400" />
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-400">
                    {it.created_at ? format(parseUtc(it.created_at), "PP p") : "—"}
                  </span>
                  <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase ${pill}`}>
                    {it.risk_level ?? "n/a"}
                  </span>
                  <span className="text-[11px] text-slate-500">
                    {Math.round((it.confidence_score ?? 0) * 100)}%
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onSelect(toReport(it, ticker))}
                    className="text-[11px] text-cyan-300 hover:text-cyan-200"
                  >
                    Load
                  </button>
                  <button
                    type="button"
                    onClick={() => toggleCompare(it.report_id)}
                    className={`text-[11px] ${inCompare ? "text-indigo-300" : "text-slate-500 hover:text-slate-300"}`}
                  >
                    Compare
                  </button>
                </div>
              </div>
              <p
                onClick={() => setExpanded(isOpen ? null : it.report_id)}
                className={`mt-1.5 cursor-pointer text-xs text-slate-300 ${isOpen ? "" : "line-clamp-2"}`}
              >
                {it.bull_case || "(no bull case)"}
              </p>
            </div>
          );
        })}
      </div>

      {compared.length === 2 && (
        <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-3">
          {compared.map((it) => (
            <div
              key={it.report_id}
              className="rounded-lg border border-[--color-border-edge] bg-[--color-bg-base]/40 p-3"
            >
              <div className="text-[11px] text-slate-500 mb-2">
                {it.created_at ? format(parseUtc(it.created_at), "PP p") : "—"}
              </div>
              <div className="text-[11px] uppercase tracking-wider text-emerald-300 mb-1">Bull</div>
              <p className="text-xs text-slate-300 mb-2">{it.bull_case}</p>
              <div className="text-[11px] uppercase tracking-wider text-red-300 mb-1">Bear</div>
              <p className="text-xs text-slate-300">{it.bear_case}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
