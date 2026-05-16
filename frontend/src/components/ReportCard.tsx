import { motion } from "framer-motion";
import { ArrowUpRight, ArrowDownRight, FileText } from "lucide-react";
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

function splitIntoPoints(text: string | null): string[] {
  if (!text) return [];
  return text
    .split(/(?<=[.!?])\s+(?=[A-Z])/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
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
          <p className="text-xs text-slate-500">Generated {ts}</p>
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

      {/* Bull / Bear two-column */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-xl border-l-4 border-emerald-500 bg-emerald-500/[0.04] p-4">
          <h3 className="font-semibold text-emerald-300 mb-3 flex items-center gap-2 text-sm uppercase tracking-wider">
            <ArrowUpRight size={16} /> Bull case
          </h3>
          {bullPoints.length === 0 ? (
            <p className="text-sm text-slate-500">No bull case available.</p>
          ) : (
            <ul className="space-y-2">
              {bullPoints.map((p, i) => (
                <li key={i} className="text-sm text-slate-200 flex gap-2">
                  <ArrowUpRight
                    size={14}
                    className="text-emerald-400 shrink-0 mt-0.5"
                  />
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="rounded-xl border-l-4 border-red-500 bg-red-500/[0.04] p-4">
          <h3 className="font-semibold text-red-300 mb-3 flex items-center gap-2 text-sm uppercase tracking-wider">
            <ArrowDownRight size={16} /> Bear case
          </h3>
          {bearPoints.length === 0 ? (
            <p className="text-sm text-slate-500">No bear case available.</p>
          ) : (
            <ul className="space-y-2">
              {bearPoints.map((p, i) => (
                <li key={i} className="text-sm text-slate-200 flex gap-2">
                  <ArrowDownRight
                    size={14}
                    className="text-red-400 shrink-0 mt-0.5"
                  />
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Citations */}
      {report.sources && report.sources.length > 0 && (
        <div className="mt-5 pt-4 border-t border-[--color-border-edge]">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 mb-2 flex items-center gap-1.5">
            <FileText size={11} /> Sources
          </div>
          <div className="flex flex-wrap gap-1.5">
            {report.sources.map((s, i) => (
              <span
                key={i}
                className="text-[11px] px-2 py-1 rounded-md bg-[--color-bg-base]/80 border border-[--color-border-edge] text-slate-400 font-mono"
              >
                {typeof s === "string" ? s : JSON.stringify(s)}
              </span>
            ))}
          </div>
        </div>
      )}
    </motion.section>
  );
}
