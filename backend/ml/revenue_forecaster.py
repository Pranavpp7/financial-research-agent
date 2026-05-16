"""
Revenue Forecaster v2 -- median quarter-over-quarter growth rate.

For each company with >= 4 quarters of non-null revenue:
  1. Compute QoQ growth rates from the full series.
  2. Forecast next quarter = last revenue * (1 + median growth).
  3. +/- 1 stdev of growth rates for the interval.
  4. MAPE on the last quarter as holdout: re-derive the median
     growth from the truncated series and predict the held-out point.

Honest at this data scale (4-7 quarterly points). Replaces the earlier
Prophet-based implementation, which over-parameterized for short series.
"""
import math

import numpy as np
import pandas as pd
import mlflow
from dotenv import load_dotenv

from backend.db.session import SessionLocal
from backend.db.models import Company, Earning
from backend.db.crud import save_ml_prediction
from backend.ingestion.pipeline import safe_float

load_dotenv()


MIN_QUARTERS = 4


def _build_company_series(db, company: Company) -> pd.DataFrame | None:
    """(ds, y) dataframe of positive-revenue history, sorted oldest -> newest."""
    earnings = (
        db.query(Earning)
        .filter(
            Earning.company_id == company.id,
            Earning.revenue.isnot(None),
            Earning.report_date.isnot(None),
        )
        .order_by(Earning.report_date.asc())
        .all()
    )
    rows = [
        {"ds": e.report_date, "y": float(e.revenue)}
        for e in earnings
        if e.revenue is not None and e.revenue > 0
    ]
    if len(rows) < MIN_QUARTERS:
        return None
    df = pd.DataFrame(rows)
    df["ds"] = pd.to_datetime(df["ds"])
    return df


def _growth_rates(revenues: list[float]) -> list[float]:
    """QoQ growth: (r_i - r_{i-1}) / r_{i-1}."""
    return [
        (revenues[i] - revenues[i - 1]) / revenues[i - 1]
        for i in range(1, len(revenues))
        if revenues[i - 1] != 0
    ]


def _quarter_string(d: pd.Timestamp) -> str:
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def forecast_company(df: pd.DataFrame) -> dict:
    """
    Returns forecast + MAPE for one company. Returns {'error': str}
    only on degenerate inputs (caller filters MIN_QUARTERS, so this
    is mostly defensive).
    """
    revenues = df["y"].tolist()
    last_revenue = revenues[-1]
    last_ds = df["ds"].max()

    # ── Holdout MAPE: predict the last quarter from prior history
    train = revenues[:-1]
    train_growths = _growth_rates(train)
    if train_growths and last_revenue:
        median_train = float(np.median(train_growths))
        predicted_last = train[-1] * (1 + median_train)
        mape = abs(last_revenue - predicted_last) / abs(last_revenue)
    else:
        mape = float("inf")

    # ── Full-history forecast
    growths = _growth_rates(revenues)
    if not growths:
        return {"error": "no usable growth rates"}
    median_growth = float(np.median(growths))
    growth_std = float(np.std(growths, ddof=1)) if len(growths) > 1 else 0.0

    forecast_revenue = last_revenue * (1 + median_growth)
    lower_bound = last_revenue * (1 + median_growth - growth_std)
    upper_bound = last_revenue * (1 + median_growth + growth_std)

    next_ds = last_ds + pd.DateOffset(months=3)

    return {
        "quarters_used": len(revenues),
        "median_growth_rate": median_growth,
        "growth_std": growth_std,
        "forecast_ds": next_ds,
        "forecast_quarter": _quarter_string(next_ds),
        "forecast_revenue": float(forecast_revenue),
        "lower_bound": float(lower_bound),
        "upper_bound": float(upper_bound),
        "mape": float(mape),
        "last_actual_revenue": float(last_revenue),
        "last_quarter_ds": last_ds,
    }


def main():
    print("Loading companies and revenue history from PostgreSQL...")
    db = SessionLocal()
    try:
        series_by_company = {}
        for company in db.query(Company).all():
            series = _build_company_series(db, company)
            if series is not None:
                series_by_company[company.id] = (company, series)
    finally:
        db.close()

    eligible = len(series_by_company)
    print(f"  {eligible} companies have >= {MIN_QUARTERS} quarters of revenue data")
    if eligible == 0:
        print("Nothing to forecast. Run the ingestion pipeline first.")
        return

    print("Forecasting via median QoQ growth rate...")
    results = []
    failures = []
    for company_id, (company, df) in series_by_company.items():
        out = forecast_company(df)
        if "error" in out:
            failures.append((company.ticker, out["error"]))
            continue
        out["company_id"] = company_id
        out["ticker"] = company.ticker
        results.append(out)

    if not results:
        print("No usable forecasts produced.")
        for t, err in failures:
            print(f"  {t}: {err}")
        return

    mapes = [r["mape"] for r in results if math.isfinite(r["mape"])]
    growths = [r["median_growth_rate"] for r in results]

    # ── MLflow ──────────────────────────────────────
    print("Logging run to MLflow...")
    mlflow.set_experiment("revenue_forecaster_v2")
    with mlflow.start_run():
        mlflow.log_params({
            "method": "median_qoq_growth",
            "min_quarters": MIN_QUARTERS,
            "interval_width_stdevs": 1,
        })
        mlflow.log_metric("companies_forecasted", len(results))
        mlflow.log_metric("companies_failed", len(failures))
        if mapes:
            mlflow.log_metric("mape_mean", float(np.mean(mapes)))
            mlflow.log_metric("mape_median", float(np.median(mapes)))
            mlflow.log_metric("mape_min", float(np.min(mapes)))
            mlflow.log_metric("mape_max", float(np.max(mapes)))
        if growths:
            mlflow.log_metric("median_growth_mean", float(np.mean(growths)))
            mlflow.log_metric("median_growth_median", float(np.median(growths)))

    # ── Persist ─────────────────────────────────────
    print("Persisting forecasts to ml_predictions...")
    db = SessionLocal()
    saved = 0
    try:
        for r in results:
            mape = r["mape"] if math.isfinite(r["mape"]) else 1.0
            confidence = max(0.0, min(1.0, 1.0 - mape))
            save_ml_prediction(db, r["company_id"], {
                "model_name": "revenue_forecaster",
                "prediction": safe_float(r["forecast_revenue"]),
                "confidence": safe_float(confidence),
                "shap_values": {
                    "forecast_quarter": r["forecast_quarter"],
                    "forecast_revenue": safe_float(r["forecast_revenue"]),
                    "lower_bound": safe_float(r["lower_bound"]),
                    "upper_bound": safe_float(r["upper_bound"]),
                    "median_growth_rate": safe_float(r["median_growth_rate"]),
                    "mape": safe_float(r["mape"]),
                    "quarters_used": r["quarters_used"],
                },
                "features_used": {
                    "ticker": r["ticker"],
                    "last_actual_revenue": safe_float(r["last_actual_revenue"]),
                    "last_quarter_ds": str(r["last_quarter_ds"].date()),
                    "growth_std": safe_float(r["growth_std"]),
                },
            })
            saved += 1
    finally:
        db.close()

    # ── Summary ─────────────────────────────────────
    print(f"\n{'='*108}")
    print(f"Revenue Forecaster v2 -- median QoQ growth")
    print(f"{'='*108}")
    print(f"  Eligible companies:   {eligible}")
    print(f"  Companies forecasted: {len(results)}")
    print(f"  Companies failed:     {len(failures)}")
    print(f"  Predictions saved:    {saved}")
    if mapes:
        print(
            f"  MAPE  mean={np.mean(mapes):.2%}  "
            f"median={np.median(mapes):.2%}  "
            f"min={np.min(mapes):.2%}  max={np.max(mapes):.2%}"
        )
    print()
    print(
        f"  {'Ticker':<8} {'Forecast':<10} {'Last actual':>18}  "
        f"{'Forecast':>18}  {'Lower':>18}  {'Upper':>18}  "
        f"{'Growth':>8}  {'MAPE':>7}  {'Conf':>6}"
    )
    print(
        f"  {'-'*8} {'-'*10} {'-'*18}  {'-'*18}  {'-'*18}  {'-'*18}  "
        f"{'-'*8}  {'-'*7}  {'-'*6}"
    )
    for r in sorted(results, key=lambda x: x["mape"]):
        mape = r["mape"] if math.isfinite(r["mape"]) else 1.0
        confidence = max(0.0, min(1.0, 1.0 - mape))
        print(
            f"  {r['ticker']:<8} {r['forecast_quarter']:<10} "
            f"${r['last_actual_revenue']:>17,.0f}  "
            f"${r['forecast_revenue']:>17,.0f}  "
            f"${r['lower_bound']:>17,.0f}  "
            f"${r['upper_bound']:>17,.0f}  "
            f"{r['median_growth_rate']:>+8.2%}  "
            f"{r['mape']:>7.2%}  {confidence:>6.3f}"
        )

    if failures:
        print(f"\n  Failures:")
        for t, err in failures:
            print(f"    {t}: {err}")
    print(f"{'='*108}\n")


if __name__ == "__main__":
    main()
