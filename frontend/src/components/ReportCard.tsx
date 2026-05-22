import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  ChevronDown,
  FileText,
  Newspaper,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import type { Report } from "../api/client";

const RISK_THEME: Record<
  string,
  { ring: string; glow: string; text: string; label: string }
> = {
  low: {
    ring: "ring-emerald-500/40",
    glow: "shadow-[0_0_16px_rgba(16,185,129,0.35)]",
    text: "text-emerald-300",
    label: "LOW RISK",
  },
  medium: {
    ring: "ring-amber-500/40",
    glow: "shadow-[0_0_16px_rgba(245,158,11,0.35)]",
    text: "text-amber-300",
    label: "MEDIUM RISK",
  },
  high: {
    ring: "ring-red-500/40",
    glow: "shadow-[0_0_16px_rgba(239,68,68,0.4)]",
    text: "text-red-300",
    label: "HIGH RISK",
  },
};

function ConfidenceRing({ value }: { value: number }) {
  // value in [0, 1]
  const size = 84;
  const stroke = 7;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.max(0, Math.min(1, value)));
  const pct = Math.round(value * 100);
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="#1e1e2e"
          strokeWidth={stroke}
          fill="none"
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="url(#confGradient)"
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          initial={{ strokeDasharray: circumference, strokeDashoffset: circumference }}
          animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1.2, ease: "easeOut" }}
        />
        <defs>
          <linearGradient id="confGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#6366f1" />
            <stop offset="100%" stopColor="#22d3ee" />
          </linearGradient>
        </defs>
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-xl font-bold text-slate-100">{pct}%</span>
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          conf
        </span>
      </div>
    </div>
  );
}

function DataQualityDot({ value }: { value: number | null }) {
  if (value === null || value === undefined) return null;
  const pct = Math.round(value * 100);
  const tone =
    value >= 0.66
      ? { dot: "bg-emerald-400", text: "text-emerald-300" }
      : value >= 0.33
        ? { dot: "bg-amber-400", text: "text-amber-300" }
        : { dot: "bg-red-400", text: "text-red-300" };
  return (
    <div className="flex items-center gap-1.5 text-xs">
      <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
      <span className={tone.text}>Data quality: {pct}%</span>
    </div>
  );
}

// Split a paragraph into sentence-ish points so each renders as a bullet.
function splitIntoPoints(text: string | null): string[] {
  if (!text) return [];
  return text
    .split(/(?<=[.!?])\s+(?=[A-Z(])/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

// Highlight inline "(source: ...)" tags as chips, keeping the rest as text.
function renderWithSourceTags(text: string, chipClass: string) {
  const parts = text.split(/(\(source:[^)]*\))/gi);
  return parts.map((part, i) =>
    /^\(source:/i.test(part) ? (
      <span
        key={i}
        className={`mx-0.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-mono align-middle ${chipClass}`}
      >
        {part.replace(/^\(source:\s*/i, "").replace(/\)$/, "")}
      </span>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

type SignalTone = "good" | "bad" | "warn" | "neutral" | "unknown";

const SIGNAL_TONE: Record<SignalTone, string> = {
  good: "border-emerald-500/30 bg-emerald-500/[0.06] text-emerald-300",
  bad: "border-red-500/30 bg-red-500/[0.06] text-red-300",
  warn: "border-amber-500/30 bg-amber-500/[0.06] text-amber-300",
  neutral: "border-slate-500/30 bg-slate-500/[0.06] text-slate-300",
  unknown: "border-[--color-border-edge] bg-[--color-bg-base]/60 text-slate-500",
};

interface Signal {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone: SignalTone;
}

// Best-effort parse of ML signals from report.sources / findings text.
// NOTE: this is a keyword heuristic; real ML fields get wired in a follow-up.
function parseSignals(report: Report): Signal[] {
  const hay = [
    ...((report.sources ?? []) as unknown[]).map((s) =>
      typeof s === "string" ? s : JSON.stringify(s)
    ),
    ...(report.key_findings ?? []),
    report.bull_case ?? "",
    report.bear_case ?? "",
  ]
    .join(" ")
    .toLowerCase();

  const earnings: Signal = {
    icon: <TrendingUp size={13} />,
    label: "Earnings",
    value: /\bbeat/.test(hay) ? "Beat" : /\bmiss/.test(hay) ? "Miss" : "—",
    tone: /\bbeat/.test(hay) ? "good" : /\bmiss/.test(hay) ? "bad" : "unknown",
  };
  const anomaly: Signal = {
    icon: <Activity size={13} />,
    label: "Anomaly",
    value: /flag|anomal/.test(hay)
      ? "Flagged"
      : /\bclean\b|no anomal/.test(hay)
        ? "Clean"
        : "—",
    tone: /flag|anomal/.test(hay)
      ? "bad"
      : /\bclean\b|no anomal/.test(hay)
        ? "good"
        : "unknown",
  };
  const beneish: Signal = {
    icon: <ShieldAlert size={13} />,
    label: "Beneish",
    value: /manipulat/.test(hay)
      ? "Manipulator"
      : /grey|gray/.test(hay)
        ? "Grey"
        : /\bclean\b/.test(hay)
          ? "Clean"
          : "—",
    tone: /manipulat/.test(hay)
      ? "bad"
      : /grey|gray/.test(hay)
        ? "warn"
        : /\bclean\b/.test(hay)
          ? "good"
          : "unknown",
  };
  const sentiment: Signal = {
    icon: <Newspaper size={13} />,
    label: "News",
    value: /positive/.test(hay)
      ? "Positive"
      : /negative/.test(hay)
        ? "Negative"
        : /neutral/.test(hay)
          ? "Neutral"
          : "—",
    tone: /positive/.test(hay)
      ? "good"
      : /negative/.test(hay)
        ? "bad"
        : /neutral/.test(hay)
          ? "neutral"
          : "unknown",
  };

  return [earnings, anomaly, beneish, sentiment];
}

function SignalChip({ signal }: { signal: Signal }) {
  return (
    <div
      className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${SIGNAL_TONE[signal.tone]}`}
    >
      {signal.icon}
      <span className="uppercase tracking-wider text-[10px] text-slate-400">
        {signal.label}
      </span>
      <span className="font-semibold">{signal.value}</span>
    </div>
  );
}

// Collapsible wrapper: header toggles an AnimatePresence-driven body.
function Collapsible({
  title,
  icon,
  defaultOpen = true,
  headerClass = "text-slate-300",
  children,
}: {
  title: React.ReactNode;
  icon?: React.ReactNode;
  defaultOpen?: boolean;
  headerClass?: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`flex w-full items-center justify-between gap-2 text-sm font-semibold uppercase tracking-wider ${headerClass}`}
      >
        <span className="flex items-center gap-2">
          {icon}
          {title}
        </span>
        <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}>
          <ChevronDown size={16} />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <div className="pt-3">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

interface Props {
  report: Report;
}

export default function ReportCard({ report }: Props) {
  const risk = (report.risk_level ?? "low") as keyof typeof RISK_THEME;
  const theme = RISK_THEME[risk] ?? RISK_THEME.low;
  const ts = report.generated_at
    ? new Date(report.generated_at).toLocaleString()
    : "—";
  const conf = report.confidence_score ?? 0;
  const bullPoints = splitIntoPoints(report.bull_case);
  const bearPoints = splitIntoPoints(report.bear_case);
  const findings = report.key_findings ?? [];
  const signals = parseSignals(report);
  const notes = (report.analyst_notes ?? "").trim();
  const sources = (report.sources ?? []) as unknown[];

  return (
    <motion.section
      initial={{ opacity: 0, y: 48 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: "easeOut" }}
      className="glass border border-[--color-border-edge] rounded-2xl p-6"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-6 flex-wrap mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h2 className="text-3xl font-bold text-slate-100 tracking-tight">
              {report.company_name || report.ticker}
            </h2>
            <span className="font-mono text-xs px-2 py-0.5 rounded-md bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
              {report.ticker}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <p className="text-xs text-slate-500">Generated {ts}</p>
            <DataQualityDot value={report.data_quality} />
          </div>
        </div>

        <div className="flex items-center gap-5">
          <motion.span
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.2, type: "spring", stiffness: 200 }}
            className={`
              px-3 py-1.5 rounded-full text-[11px] font-bold tracking-widest uppercase
              bg-[--color-bg-base]/80 ring-1 ${theme.ring} ${theme.text} ${theme.glow}
            `}
          >
            {theme.label}
          </motion.span>
          <ConfidenceRing value={conf} />
        </div>
      </div>

      {/* ML signals row */}
      <div className="flex flex-wrap gap-2 mb-6">
        {signals.map((s) => (
          <SignalChip key={s.label} signal={s} />
        ))}
      </div>

      {/* Bull / Bear two-column (each collapsible) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-xl border-l-4 border-emerald-500 bg-emerald-500/[0.04] p-4">
          <Collapsible
            title="Bull case"
            icon={<ArrowUpRight size={16} />}
            headerClass="text-emerald-300"
          >
            {bullPoints.length === 0 ? (
              <p className="text-sm text-slate-500">No bull case available.</p>
            ) : (
              <ul className="space-y-2">
                {bullPoints.map((p, i) => (
                  <li key={i} className="text-sm text-slate-200 flex gap-2">
                    <ArrowUpRight size={14} className="text-emerald-400 shrink-0 mt-0.5" />
                    <span>
                      {renderWithSourceTags(
                        p,
                        "bg-emerald-400/15 text-emerald-200"
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Collapsible>
        </div>

        <div className="rounded-xl border-l-4 border-red-500 bg-red-500/[0.04] p-4">
          <Collapsible
            title="Bear case"
            icon={<ArrowDownRight size={16} />}
            headerClass="text-red-300"
          >
            {bearPoints.length === 0 ? (
              <p className="text-sm text-slate-500">No bear case available.</p>
            ) : (
              <ul className="space-y-2">
                {bearPoints.map((p, i) => (
                  <li key={i} className="text-sm text-slate-200 flex gap-2">
                    <ArrowDownRight size={14} className="text-red-400 shrink-0 mt-0.5" />
                    <span>
                      {renderWithSourceTags(p, "bg-red-400/15 text-red-200")}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Collapsible>
        </div>
      </div>

      {/* Key findings */}
      {findings.length > 0 && (
        <div className="mt-6">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2">
            Key findings
          </div>
          <ol className="space-y-2">
            {findings.map((f, i) => (
              <li
                key={i}
                className="flex gap-3 rounded-lg border-l-2 border-indigo-500/50 bg-[--color-bg-base]/40 px-3 py-2"
              >
                <span className="font-mono text-xs text-indigo-300 mt-0.5">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="text-sm text-slate-200">{f}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Analyst notes */}
      {notes && (
        <div className="mt-6 flex gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/[0.06] p-4">
          <AlertTriangle size={16} className="text-amber-300 shrink-0 mt-0.5" />
          <p className="text-sm italic text-amber-100/90">{notes}</p>
        </div>
      )}

      {/* Sources accordion (collapsed by default) */}
      {sources.length > 0 && (
        <div className="mt-5 pt-4 border-t border-[--color-border-edge]">
          <Collapsible
            title={`Sources (${sources.length})`}
            icon={<FileText size={13} />}
            defaultOpen={false}
            headerClass="text-slate-500"
          >
            <div className="flex flex-wrap gap-1.5">
              {sources.map((s, i) => (
                <span
                  key={i}
                  className="text-[11px] px-2 py-1 rounded-md bg-[--color-bg-base]/80 border border-[--color-border-edge] text-slate-400 font-mono"
                >
                  {typeof s === "string" ? s : JSON.stringify(s)}
                </span>
              ))}
            </div>
          </Collapsible>
        </div>
      )}
    </motion.section>
  );
}
