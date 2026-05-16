import { useEffect, useState } from "react";
import { fetchCompanies, type Company } from "../api/client";

interface Props {
  onSelect: (ticker: string) => void;
}

export default function CompanyList({ onSelect }: Props) {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchCompanies()
      .then(setCompanies)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="bg-white rounded-lg shadow p-4 border border-slate-200">
      <h3 className="text-lg font-semibold text-slate-800 mb-3">
        Companies{!loading && ` (${companies.length})`}
      </h3>

      {loading && (
        <p className="text-sm text-slate-500">Loading companies...</p>
      )}
      {error && (
        <p className="text-sm text-red-600">
          Could not load companies: {error}
        </p>
      )}
      {!loading && companies.length === 0 && !error && (
        <p className="text-sm text-slate-500">
          No companies in database. Run the ingestion pipeline.
        </p>
      )}

      <ul className="max-h-[420px] overflow-auto divide-y divide-slate-100">
        {companies.map((c) => (
          <li key={c.ticker}>
            <button
              type="button"
              onClick={() => onSelect(c.ticker)}
              className="w-full text-left py-2 px-2 hover:bg-slate-50 rounded transition"
            >
              <span className="font-mono text-sm font-semibold text-slate-900">
                {c.ticker}
              </span>
              {c.name && (
                <span className="ml-2 text-sm text-slate-600">{c.name}</span>
              )}
              {c.sector && (
                <div className="text-xs text-slate-400 mt-0.5">
                  {c.sector}
                </div>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
