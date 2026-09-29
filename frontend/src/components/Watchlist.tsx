import { useEffect, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import { Bell, CalendarClock, Plus, X } from "lucide-react";
import AlertSettings from "./AlertSettings";
import {
  addToWatchlist,
  getScheduleStatus,
  getWatchlistSummary,
  parseUtc,
  removeFromWatchlist,
  type ScheduleStatus,
  type WatchlistSummaryItem,
} from "../api/client";

const RISK_PILL: Record<string, string> = {
  low: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  medium: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  high: "bg-red-500/15 text-red-300 border-red-500/30",
};

interface Props {
  refreshKey: number; // bump to force a reload (e.g. after an analysis completes)
  onAnalyze: (ticker: string) => void;
}

export default function Watchlist({ refreshKey, onAnalyze }: Props) {
  const [items, setItems] = useState<WatchlistSummaryItem[]>([]);
  const [newTicker, setNewTicker] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [schedule, setSchedule] = useState<ScheduleStatus | null>(null);
  const [alertsFor, setAlertsFor] = useState<string | null>(null);

  const load = async () => {
    try {
      setItems(await getWatchlistSummary());
    } catch {
      /* keep last state on transient errors */
    }
    try {
      setSchedule(await getScheduleStatus());
    } catch {
      /* schedule status is best-effort */
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  const handleAdd = async () => {
    const t = newTicker.trim().toUpperCase();
    if (!t) return;
    setError(null);
    setAdding(true);
    try {
      await addToWatchlist(t);
      setNewTicker("");
      await load();
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Could not add ticker";
      setError(detail);
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (ticker: string) => {
    await removeFromWatchlist(ticker);
    await load();
  };

  // Most-recently-analyzed first; never-analyzed at the bottom.
  const sorted = [...items].sort((a, b) => {
    const ta = a.last_analyzed ? Date.parse(a.last_analyzed) : -Infinity;
    const tb = b.last_analyzed ? Date.parse(b.last_analyzed) : -Infinity;
    return tb - ta;
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
          Watchlist
        </h2>
      </div>

      <div className="flex gap-1.5">
        <input
          value={newTicker}
          onChange={(e) => setNewTicker(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="Add ticker"
          className="
            flex-1 min-w-0 bg-bg-base/70 border border-border-edge
            rounded-lg px-2.5 py-1.5 text-xs font-mono uppercase text-slate-100
            placeholder:normal-case placeholder:text-slate-600
            focus:outline-none focus:border-indigo-500/60
          "
        />
        <button
          type="button"
          onClick={handleAdd}
          disabled={adding || !newTicker.trim()}
          className="flex items-center gap-1 rounded-lg bg-indigo-500/20 border border-indigo-500/30 px-2.5 py-1.5 text-xs text-indigo-200 hover:bg-indigo-500/30 disabled:opacity-40"
        >
          <Plus size={13} /> Add
        </button>
      </div>
      {error && <p className="text-[11px] text-red-400">{error}</p>}

      <div className="flex flex-col gap-2">
        {sorted.length === 0 && (
          <p className="text-xs text-slate-600">No tickers yet.</p>
        )}
        {sorted.map((it) => {
          const risk = it.risk_level ?? null;
          const pill = risk ? RISK_PILL[risk] : "bg-slate-500/15 text-slate-400 border-slate-500/30";
          return (
            <div
              key={it.ticker}
              className="rounded-lg border border-border-edge bg-bg-base/40 p-2.5"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono font-semibold text-slate-100">{it.ticker}</span>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setAlertsFor(it.ticker)}
                    className="text-slate-500 hover:text-indigo-300"
                    aria-label={`alerts for ${it.ticker}`}
                  >
                    <Bell size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleRemove(it.ticker)}
                    className="text-slate-500 hover:text-red-400"
                    aria-label={`remove ${it.ticker}`}
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
              {it.notes && (
                <p className="mt-0.5 text-[11px] italic text-slate-500">{it.notes}</p>
              )}
              <div className="mt-1.5 flex items-center gap-2 flex-wrap">
                <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider ${pill}`}>
                  {risk ?? "n/a"}
                </span>
                {it.confidence_score !== null && (
                  <span className="text-[10px] text-slate-500">
                    {Math.round((it.confidence_score ?? 0) * 100)}%
                  </span>
                )}
                <span className="text-[10px] text-slate-600">
                  {it.last_analyzed
                    ? formatDistanceToNow(parseUtc(it.last_analyzed), { addSuffix: true })
                    : "never analyzed"}
                </span>
              </div>
              <button
                type="button"
                onClick={() => onAnalyze(it.ticker)}
                className="mt-2 text-[11px] text-cyan-300 hover:text-cyan-200"
              >
                Analyze →
              </button>
            </div>
          );
        })}
      </div>

      {schedule?.beat_running && (
        <div className="mt-1 rounded-lg border border-indigo-500/25 bg-indigo-500/[0.06] px-2.5 py-2 text-[11px] text-indigo-200">
          <div className="flex items-center gap-1.5">
            <CalendarClock size={12} /> Auto-analyzing nightly
          </div>
          {schedule.next_runs?.["nightly-watchlist-reanalysis"] && (
            <div className="mt-0.5 text-[10px] text-slate-500">
              Next run:{" "}
              {formatDistanceToNow(
                parseUtc(schedule.next_runs["nightly-watchlist-reanalysis"]),
                { addSuffix: true }
              )}
            </div>
          )}
        </div>
      )}

      {alertsFor && (
        <AlertSettings ticker={alertsFor} onClose={() => setAlertsFor(null)} />
      )}
    </div>
  );
}
