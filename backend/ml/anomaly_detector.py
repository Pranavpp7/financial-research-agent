"""
Financial Anomaly Detector.

Fits an Isolation Forest over per-quarter financial feature rows pulled
from the earnings table, scores each company's most recent quarter,
and writes one ml_predictions row per company.
"""
import pandas as pd
import mlflow
import mlflow.sklearn
from dotenv import load_dotenv
from sklearn.ensemble import IsolationForest

from backend.db.session import SessionLocal
from backend.db.models import Company, Earning
from backend.db.crud import save_ml_prediction
from backend.ingestion.pipeline import safe_float

load_dotenv()


# Only features that are actually persisted on the Earning model.
# debt_to_assets and cash_flow_ratio come from yfinance ratios but
# aren't stored yet -- skipped per "if available, else skip".
FEATURE_COLS = [
    "operating_margin",
    "revenue_growth_qoq",
    "surprise_pct",
]

CONTAMINATION = 0.1
ANOMALY_THRESHOLD = -0.1
N_ESTIMATORS = 100
RANDOM_STATE = 42


def _earning_to_dict(e: Earning) -> dict:
    return {
        "quarter": e.quarter,
        "report_date": e.report_date,
        "revenue": e.revenue,
        "operating_margin": e.operating_margin,
        "surprise_pct": e.surprise_pct,
    }


def build_feature_dataset() -> pd.DataFrame:
    """
    One row per (company, quarter) where revenue growth is computable
    AND every feature is non-null. Sorted oldest -> newest within company.
    """
    db = SessionLocal()
    try:
        rows = []
        for company in db.query(Company).all():
            earnings = (
                db.query(Earning)
                .filter(Earning.company_id == company.id)
                .order_by(Earning.report_date.asc())
                .all()
            )
            history = [_earning_to_dict(e) for e in earnings]
            for i, current in enumerate(history):
                if i == 0:
                    continue  # growth needs a prior quarter
                prior = history[i - 1]
                if (
                    current["revenue"] is None
                    or prior["revenue"] is None
                    or prior["revenue"] == 0
                ):
                    continue
                growth = (
                    (current["revenue"] - prior["revenue"])
                    / abs(prior["revenue"])
                    * 100
                )
                row = {
                    "company_id": company.id,
                    "ticker": company.ticker,
                    "quarter": current["quarter"],
                    "report_date": current["report_date"],
                    "operating_margin": current["operating_margin"],
                    "revenue_growth_qoq": growth,
                    "surprise_pct": current["surprise_pct"],
                }
                if any(row[c] is None for c in FEATURE_COLS):
                    continue
                rows.append(row)
        return pd.DataFrame(rows)
    finally:
        db.close()


def feature_contributions(
    features: dict, means: dict, stds: dict
) -> dict:
    """
    Per-feature signed z-score relative to the training distribution.
    Larger absolute value -> that feature is further from typical and
    contributed more to the anomaly score.
    """
    contribs = {}
    for col in FEATURE_COLS:
        std = stds.get(col) or 0
        mean = means.get(col) or 0
        if std == 0 or features[col] is None:
            contribs[col] = 0.0
        else:
            contribs[col] = safe_float((features[col] - mean) / std)
    return contribs


def main():
    print("Loading earnings feature dataset from PostgreSQL...")
    df = build_feature_dataset()
    n_companies = df["ticker"].nunique() if not df.empty else 0
    print(
        f"  built {len(df)} (company, quarter) feature rows "
        f"across {n_companies} tickers"
    )

    if len(df) < 5:
        print(
            "Not enough rows to fit IsolationForest (need >= 5). "
            "Run the ingestion pipeline on more tickers first."
        )
        return

    X = df[FEATURE_COLS].astype(float)

    print(f"Training IsolationForest (contamination={CONTAMINATION})...")
    model = IsolationForest(
        n_estimators=N_ESTIMATORS,
        contamination=CONTAMINATION,
        random_state=RANDOM_STATE,
    )
    model.fit(X)

    df["anomaly_score"] = model.decision_function(X)
    df["is_anomaly"] = (df["anomaly_score"] < ANOMALY_THRESHOLD).astype(int)

    means = X.mean().to_dict()
    stds = X.std().to_dict()

    print("Logging run to MLflow...")
    mlflow.set_experiment("anomaly_detector")
    with mlflow.start_run():
        mlflow.log_params({
            "n_estimators": N_ESTIMATORS,
            "contamination": CONTAMINATION,
            "random_state": RANDOM_STATE,
            "anomaly_threshold": ANOMALY_THRESHOLD,
            "features": ",".join(FEATURE_COLS),
        })
        mlflow.log_metric("rows_total", len(df))
        mlflow.log_metric("rows_flagged", int(df["is_anomaly"].sum()))
        mlflow.log_metric("companies_total", n_companies)
        mlflow.log_metric("score_mean", float(df["anomaly_score"].mean()))
        mlflow.log_metric("score_min", float(df["anomaly_score"].min()))
        mlflow.sklearn.log_model(model, "model")

    # One prediction per company: their most recent quarter
    latest = (
        df.sort_values(["company_id", "report_date"], ascending=[True, False])
          .drop_duplicates(subset="company_id", keep="first")
    )

    print("Persisting per-company predictions...")
    saved = 0
    flagged = []
    db = SessionLocal()
    try:
        for _, row in latest.iterrows():
            features = {col: row[col] for col in FEATURE_COLS}
            contribs = feature_contributions(features, means, stds)
            score = float(row["anomaly_score"])
            is_anom = bool(score < ANOMALY_THRESHOLD)

            save_ml_prediction(db, int(row["company_id"]), {
                "model_name": "anomaly_detector",
                "prediction": safe_float(score),
                "confidence": 1.0 if is_anom else 0.0,
                "shap_values": contribs,
                "features_used": {
                    col: safe_float(features[col]) for col in FEATURE_COLS
                },
            })
            saved += 1

            if is_anom:
                top_feat, top_z = max(
                    contribs.items(),
                    key=lambda kv: abs(kv[1] or 0),
                )
                flagged.append({
                    "ticker": row["ticker"],
                    "quarter": row["quarter"],
                    "score": score,
                    "driver": top_feat,
                    "driver_z": top_z,
                    "feature_values": features,
                })
    finally:
        db.close()

    print(f"\n{'='*70}")
    print(f"Anomaly Detector")
    print(f"{'='*70}")
    print(f"  Training rows:       {len(df)}")
    print(f"  Companies scored:    {saved}")
    print(
        f"  Anomalies flagged:   {len(flagged)}  "
        f"(threshold: score < {ANOMALY_THRESHOLD})"
    )

    if flagged:
        print(f"\n  Flagged companies:")
        for f in flagged:
            print(
                f"    {f['ticker']:8s} {f['quarter']:8s}  "
                f"score={f['score']:+.4f}  "
                f"driver={f['driver']} (z={f['driver_z']:+.2f})"
            )
            for col, val in f["feature_values"].items():
                marker = "  <-- driver" if col == f["driver"] else ""
                print(f"      {col:22s} {val:+.4f}{marker}")
    else:
        print(f"\n  No anomalies flagged at this threshold.")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
