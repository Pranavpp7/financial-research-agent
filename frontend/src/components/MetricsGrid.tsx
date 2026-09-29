import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Building2, TrendingUp, TrendingDown, FileText, Cpu } from "lucide-react";
import { fetchStats, type Stats } from "../api/client";

type Tone = "indigo" | "cyan" | "emerald" | "red" | "amber";

const TONE_GRADIENT: Record<Tone, string> = {
  indigo: "from-indigo-500/60 to-indigo-500/0",
  cyan: "from-cyan-400/60 to-cyan-400/0",
  emerald: "from-emerald-500/60 to-emerald-500/0",
  red: "from-red-500/60 to-red-500/0",
  amber: "from-amber-500/60 to-amber-500/0",
};

const TONE_ICON: Record<Tone, string> = {
  indigo: "text-indigo-400",
  cyan: "text-cyan-400",
  emerald: "text-emerald-400",
  red: "text-red-400",
  amber: "text-amber-400",
};

interface CardProps {
  icon: React.ReactNode;
  value: string;
  label: string;
  trend?: "up" | "down" | null;
  tone: Tone;
  delay?: number;
}

function MetricCard({ icon, value, label, trend, tone, delay = 0 }: CardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay, ease: "easeOut" }}
      className="relative rounded-2xl overflow-hidden group"
    >
      {/* Gradient border via mask */}
      <div
        className={`absolute inset-0 rounded-2xl bg-gradient-to-b ${TONE_GRADIENT[tone]} opacity-40`}
      />
      <div className="relative m-[1px] rounded-2xl glass border border-border-edge p-5 h-full">
        <div className="flex items-start justify-between mb-4">
          <div className={`${TONE_ICON[tone]}`}>{icon}</div>
          {trend && (
            <span
              className={`text-[11px] flex items-center gap-1 ${
                trend === "up" ? "text-emerald-400" : "text-red-400"
              }`}
            >
              {trend === "up" ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
              {trend === "up" ? "positive" : "negative"}
            </span>
          )}
        </div>
        <div className="text-3xl font-bold text-slate-100 mb-1 tabular-nums">
          {value}
        </div>
        <div className="text-xs uppercase tracking-widest text-slate-500">
          {label}
        </div>
      </div>
    </motion.div>
  );
}

export default function MetricsGrid() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch((e) => setError(String(e)));
  }, []);

  // Fallbacks while loading or on error -- premium UIs degrade gracefully.
  const totalCompanies = stats?.total_companies ?? 0;
  const avgSent = stats?.average_sentiment ?? null;
  const reportsToday = stats?.reports_today ?? 0;
  const modelsRunning = stats?.models_running ?? 6;

  const avgSentDisplay =
    avgSent === null || Number.isNaN(avgSent)
      ? "—"
      : (avgSent >= 0 ? "+" : "") + avgSent.toFixed(2);
  const avgTrend: "up" | "down" | null =
    avgSent === null ? null : avgSent >= 0 ? "up" : "down";

  return (
    <section className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <MetricCard
        icon={<Building2 size={22} />}
        value={totalCompanies.toString()}
        label="Companies tracked"
        tone="indigo"
        delay={0.0}
      />
      <MetricCard
        icon={
          avgTrend === "down" ? <TrendingDown size={22} /> : <TrendingUp size={22} />
        }
        value={avgSentDisplay}
        label="Avg sentiment"
        trend={avgTrend}
        tone={avgTrend === "down" ? "red" : "cyan"}
        delay={0.05}
      />
      <MetricCard
        icon={<FileText size={22} />}
        value={reportsToday.toString()}
        label="Reports today"
        tone="emerald"
        delay={0.1}
      />
      <MetricCard
        icon={<Cpu size={22} />}
        value={modelsRunning.toString()}
        label="Models running"
        tone="amber"
        delay={0.15}
      />
      {error && (
        <p className="col-span-full text-xs text-red-400">
          Stats unavailable: {error}
        </p>
      )}
    </section>
  );
}
