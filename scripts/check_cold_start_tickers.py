"""
List tickers whose earnings-surprise prediction was a cold-start sentinel.

The earnings_predictor writes a sentinel ml_predictions row (shap_values
status = "insufficient_data") for any company with fewer than
MIN_QUARTERS_REQUIRED usable quarters. This script surfaces those tickers
so you know which ones need more ingestion history before the XGBoost
model can produce a real prediction.

Usage:
  uv run --module scripts.check_cold_start_tickers
  uv run python scripts/check_cold_start_tickers.py
"""
import sys
from pathlib import Path

# Allow `python scripts/check_cold_start_tickers.py` as well as `-m ...`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import func

from backend.db.models import Company, Earning, MLPrediction
from backend.db.session import SessionLocal


def main() -> int:
    db = SessionLocal()
    try:
        # Latest earnings_surprise_predictor row per company, then keep the
        # ones flagged insufficient_data.
        latest = (
            db.query(
                MLPrediction.company_id,
                func.max(MLPrediction.run_date).label("max_date"),
            )
            .filter(MLPrediction.model_name == "earnings_surprise_predictor")
            .group_by(MLPrediction.company_id)
            .subquery()
        )
        rows = (
            db.query(MLPrediction, Company)
            .join(Company, MLPrediction.company_id == Company.id)
            .join(
                latest,
                (MLPrediction.company_id == latest.c.company_id)
                & (MLPrediction.run_date == latest.c.max_date),
            )
            .filter(MLPrediction.model_name == "earnings_surprise_predictor")
            .all()
        )

        cold = []
        for pred, company in rows:
            sv = pred.shap_values or {}
            if isinstance(sv, dict) and sv.get("status") == "insufficient_data":
                last_report = (
                    db.query(func.max(Earning.report_date))
                    .filter(Earning.company_id == company.id)
                    .scalar()
                )
                cold.append((
                    company.ticker,
                    sv.get("quarters_available"),
                    last_report.date().isoformat() if last_report else "n/a",
                ))

        print(f"\n{'='*52}")
        print(" Cold-start tickers (earnings_surprise_predictor)")
        print(f"{'='*52}")
        if not cold:
            print("  None -- every tracked company has enough history.")
            return 0

        print(f"  {'Ticker':<10} {'Quarters':>9}  {'Last report':<12}")
        print(f"  {'-'*10} {'-'*9}  {'-'*12}")
        for ticker, qtrs, last in sorted(cold, key=lambda r: (r[1] or 0)):
            print(f"  {ticker:<10} {str(qtrs):>9}  {last:<12}")
        print(f"\n  {len(cold)} ticker(s) need more ingestion history.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
