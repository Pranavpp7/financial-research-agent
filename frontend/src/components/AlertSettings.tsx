import { useEffect, useState } from "react";
import { Send, Trash2, X } from "lucide-react";
import {
  deleteAlertSubscription,
  listAlertSubscriptions,
  subscribeAlert,
  testAlert,
  type AlertSubscription,
} from "../api/client";

const TRIGGERS = [
  "risk_increased",
  "risk_decreased",
  "confidence_dropped_20pct",
  "high_risk_flagged",
];

interface Props {
  ticker: string;
  onClose: () => void;
}

export default function AlertSettings({ ticker, onClose }: Props) {
  const [subs, setSubs] = useState<AlertSubscription[]>([]);
  const [channel, setChannel] = useState<"email" | "slack">("email");
  const [destination, setDestination] = useState("");
  const [selected, setSelected] = useState<string[]>(["high_risk_flagged"]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setSubs(await listAlertSubscriptions(ticker));
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker]);

  const toggleTrigger = (t: string) =>
    setSelected((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  const handleAdd = async () => {
    setError(null);
    if (!destination.trim() || selected.length === 0) {
      setError("Destination and at least one trigger are required");
      return;
    }
    setBusy(true);
    try {
      await subscribeAlert({ ticker, channel, destination: destination.trim(), triggers: selected });
      setDestination("");
      await load();
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Could not create subscription";
      setError(detail);
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (id: number) => {
    await deleteAlertSubscription(id);
    await load();
  };

  const handleTest = async (id: number) => {
    const res = await testAlert(id);
    setError(res.sent ? `Test sent ✓` : `Test failed: ${res.error}`);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="glass border border-[--color-border-edge] rounded-2xl p-6 w-full max-w-md max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-200">
            🔔 Alerts — {ticker}
          </h3>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-200">
            <X size={18} />
          </button>
        </div>

        {/* existing subscriptions */}
        {subs.length === 0 ? (
          <p className="text-xs text-slate-500 mb-4">No alerts set up for {ticker}.</p>
        ) : (
          <div className="flex flex-col gap-2 mb-4">
            {subs.map((s) => (
              <div
                key={s.id}
                className="rounded-lg border border-[--color-border-edge] bg-[--color-bg-base]/40 p-2.5 text-xs"
              >
                <div className="flex items-center justify-between">
                  <span className="text-slate-200">
                    {s.channel} → <span className="font-mono">{s.destination}</span>
                  </span>
                  <div className="flex items-center gap-2">
                    <button onClick={() => handleTest(s.id)} className="text-cyan-300 hover:text-cyan-200" title="Send test">
                      <Send size={13} />
                    </button>
                    <button onClick={() => handleDelete(s.id)} className="text-red-400 hover:text-red-300" title="Delete">
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
                <div className="mt-1 text-[10px] text-slate-500">{(s.triggers || []).join(", ")}</div>
              </div>
            ))}
          </div>
        )}

        {/* add new */}
        <div className="border-t border-[--color-border-edge] pt-4 flex flex-col gap-2">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Add subscription</div>
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value as "email" | "slack")}
            className="bg-[--color-bg-base]/70 border border-[--color-border-edge] rounded-lg px-2.5 py-1.5 text-xs text-slate-100"
          >
            <option value="email">Email</option>
            <option value="slack">Slack webhook</option>
          </select>
          <input
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            placeholder={channel === "email" ? "you@example.com" : "https://hooks.slack.com/..."}
            className="bg-[--color-bg-base]/70 border border-[--color-border-edge] rounded-lg px-2.5 py-1.5 text-xs text-slate-100 placeholder:text-slate-600"
          />
          <div className="flex flex-col gap-1">
            {TRIGGERS.map((t) => (
              <label key={t} className="flex items-center gap-2 text-xs text-slate-300">
                <input
                  type="checkbox"
                  checked={selected.includes(t)}
                  onChange={() => toggleTrigger(t)}
                />
                {t}
              </label>
            ))}
          </div>
          {error && <p className="text-[11px] text-amber-300">{error}</p>}
          <button
            onClick={handleAdd}
            disabled={busy}
            className="mt-1 rounded-lg bg-indigo-500/20 border border-indigo-500/30 px-3 py-1.5 text-xs text-indigo-200 hover:bg-indigo-500/30 disabled:opacity-40"
          >
            Add alert
          </button>
        </div>
      </div>
    </div>
  );
}
