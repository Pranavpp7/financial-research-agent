import type { Report } from "../api/client";

const RISK_STYLES: Record<string, string> = {
  low: "bg-green-100 text-green-800 ring-1 ring-green-300",
  medium: "bg-yellow-100 text-yellow-800 ring-1 ring-yellow-300",
  high: "bg-red-100 text-red-800 ring-1 ring-red-300",
};

interface Props {
  report: Report;
}

export default function ReportCard({ report }: Props) {
  const risk = report.risk_level ?? "unknown";
  const riskClass =
    RISK_STYLES[risk] ?? "bg-gray-100 text-gray-700 ring-1 ring-gray-300";

  const confPct =
    report.confidence_score !== null && report.confidence_score !== undefined
      ? Math.round(report.confidence_score * 100)
      : null;

  const ts = report.generated_at
    ? new Date(report.generated_at).toLocaleString()
    : "—";

  return (
    <div className="bg-white rounded-lg shadow p-6 border border-slate-200">
      <div className="flex items-start justify-between mb-4 gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-slate-900">
            {report.company_name || report.ticker}
          </h2>
          <p className="text-sm text-slate-500">
            {report.ticker} · generated {ts}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2 shrink-0">
          <span
            className={`px-3 py-1 rounded-full text-xs font-semibold uppercase ${riskClass}`}
          >
            risk: {risk}
          </span>
          {confPct !== null && (
            <span className="text-xs text-slate-500">
              confidence: <strong>{confPct}%</strong>
            </span>
          )}
        </div>
      </div>

      <div className="border-l-4 border-green-500 bg-green-50 rounded-r p-4 mb-3">
        <h3 className="font-semibold text-green-900 mb-1">Bull case</h3>
        <p className="text-sm text-slate-700 whitespace-pre-wrap">
          {report.bull_case || "—"}
        </p>
      </div>

      <div className="border-l-4 border-red-500 bg-red-50 rounded-r p-4">
        <h3 className="font-semibold text-red-900 mb-1">Bear case</h3>
        <p className="text-sm text-slate-700 whitespace-pre-wrap">
          {report.bear_case || "—"}
        </p>
      </div>

      {report.sources && report.sources.length > 0 && (
        <div className="mt-4">
          <h4 className="text-xs font-semibold text-slate-500 uppercase mb-1">
            Sources
          </h4>
          <ul className="text-xs text-slate-600 list-disc list-inside space-y-0.5">
            {report.sources.map((s, i) => (
              <li key={i}>
                {typeof s === "string" ? s : JSON.stringify(s)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
