"""
Earnings Surprise Predictor.

Trains an XGBoost classifier to predict whether a company beats its EPS
estimate in the upcoming quarter, using features engineered from the
company's prior earnings history. Logs the experiment to MLflow and
persists a per-company prediction to the ml_predictions table.
"""
import os

import numpy as np
import pandas as pd
import xgboost as xgb
import shap
import mlflow
import mlflow.xgboost
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
)

from backend.db.session import SessionLocal
from backend.db.models import Company, Earning
from backend.db.crud import save_ml_prediction
from backend.ingestion.pipeline import safe_float

load_dotenv()


FEATURE_COLS = [
    "avg_surprise_3q",
    "avg_surprise_all",
    "surprise_trend",
    "beat_rate",
    "estimate_accuracy",
    "consecutive_beats",
]

# Train on quarters strictly before this; test on this and after.
TEST_QUARTER_CUTOFF = "2025-Q4"

XGB_PARAMS = {
    "n_estimators": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "random_state": 42,
}


def _surprise_pct(actual, estimate):
    """Fallback surprise % when DB column is missing."""
    if actual is None or estimate is None or estimate == 0:
        return None
    return (actual - estimate) / abs(estimate) * 100


def _earning_to_dict(e: Earning) -> dict:
    return {
        "quarter": e.quarter,
        "report_date": e.report_date,
        "eps_estimate": e.eps_estimate,
        "eps_actual": e.eps_actual,
        "surprise_pct": e.surprise_pct,
    }


def compute_features(history: list[dict]) -> dict:
    """
    Build features from a list of PRIOR earnings rows
    (sorted oldest -> newest). No leakage: caller must exclude
    the target quarter from `history`.
    """
    surprises, beats, abs_errors = [], [], []
    for row in history:
        sp = row.get("surprise_pct")
        if sp is None:
            sp = _surprise_pct(row.get("eps_actual"), row.get("eps_estimate"))
        if sp is not None:
            surprises.append(float(sp))

        actual, est = row.get("eps_actual"), row.get("eps_estimate")
        if actual is not None and est is not None:
            beats.append(1 if actual > est else 0)
            abs_errors.append(abs(float(actual) - float(est)))

    avg_surprise_all = float(np.mean(surprises)) if surprises else None
    avg_surprise_3q = float(np.mean(surprises[-3:])) if surprises else None

    if len(surprises) >= 4:
        surprise_trend = float(np.mean(surprises[-2:]) - np.mean(surprises[-4:-2]))
    else:
        surprise_trend = None

    beat_rate = float(np.mean(beats)) if beats else None
    estimate_accuracy = float(np.mean(abs_errors)) if abs_errors else None

    consecutive = 0
    for b in reversed(beats):
        if b == 1:
            consecutive += 1
        else:
            break

    return {
        "avg_surprise_3q": avg_surprise_3q,
        "avg_surprise_all": avg_surprise_all,
        "surprise_trend": surprise_trend,
        "beat_rate": beat_rate,
        "estimate_accuracy": estimate_accuracy,
        "consecutive_beats": consecutive,
    }


def load_earnings_dataset() -> pd.DataFrame:
    """
    Build a (company, quarter) training table where every row's features
    are computed only from quarters that came BEFORE it for that company.
    Drops rows where features are incomplete or target is unknown.
    """
    db = SessionLocal()
    try:
        rows = []
        companies = db.query(Company).all()
        for company in companies:
            earnings = (
                db.query(Earning)
                .filter(Earning.company_id == company.id)
                .order_by(Earning.report_date.asc())
                .all()
            )
            history = [_earning_to_dict(e) for e in earnings]

            for i, current in enumerate(history):
                actual, est, quarter = (
                    current["eps_actual"],
                    current["eps_estimate"],
                    current["quarter"],
                )
                if actual is None or est is None or quarter is None:
                    continue

                features = compute_features(history[:i])
                if any(features[c] is None for c in FEATURE_COLS):
                    continue

                rows.append({
                    "company_id": company.id,
                    "ticker": company.ticker,
                    "quarter": quarter,
                    **features,
                    "beat": 1 if actual > est else 0,
                })
        return pd.DataFrame(rows)
    finally:
        db.close()


def split_train_test(df: pd.DataFrame, cutoff: str = TEST_QUARTER_CUTOFF):
    """Quarter-based time split (lex comparison works for 'YYYY-QN')."""
    train = df[df["quarter"] < cutoff].copy()
    test = df[df["quarter"] >= cutoff].copy()
    return train, test


def train_and_evaluate(train: pd.DataFrame, test: pd.DataFrame):
    X_train, y_train = train[FEATURE_COLS], train["beat"]
    X_test, y_test = test[FEATURE_COLS], test["beat"]

    model = xgb.XGBClassifier(**XGB_PARAMS)
    model.fit(X_train, y_train)

    metrics = {}
    if len(y_test):
        preds = model.predict(X_test)
        metrics = {
            "accuracy": float(accuracy_score(y_test, preds)),
            "precision": float(precision_score(y_test, preds, zero_division=0)),
            "recall": float(recall_score(y_test, preds, zero_division=0)),
            "f1": float(f1_score(y_test, preds, zero_division=0)),
        }

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_train)
    if isinstance(shap_values, list):
        shap_values = shap_values[1]

    return model, metrics, shap_values


def log_to_mlflow(model, metrics: dict, shap_values, X_train: pd.DataFrame):
    mlflow.set_experiment("earnings_surprise_predictor")
    with mlflow.start_run():
        mlflow.log_params(XGB_PARAMS)
        for name, value in metrics.items():
            mlflow.log_metric(name, value)

        plot_path = "shap_feature_importance.png"
        plt.figure(figsize=(8, 5))
        shap.summary_plot(
            shap_values, X_train, plot_type="bar", show=False
        )
        plt.tight_layout()
        plt.savefig(plot_path, bbox_inches="tight")
        plt.close()
        mlflow.log_artifact(plot_path)
        if os.path.exists(plot_path):
            os.remove(plot_path)

        mlflow.xgboost.log_model(model, "model")


def predict_and_persist(model) -> int:
    """
    Generate a forward-looking prediction per company using ALL of that
    company's earnings as feature history, and write to ml_predictions.
    """
    db = SessionLocal()
    saved = 0
    try:
        explainer = shap.TreeExplainer(model)
        companies = db.query(Company).all()
        for company in companies:
            earnings = (
                db.query(Earning)
                .filter(Earning.company_id == company.id)
                .order_by(Earning.report_date.asc())
                .all()
            )
            history = [_earning_to_dict(e) for e in earnings]
            features = compute_features(history)
            if any(features[c] is None for c in FEATURE_COLS):
                continue

            X = pd.DataFrame([features], columns=FEATURE_COLS)
            proba = float(model.predict_proba(X)[0, 1])
            pred = int(proba >= 0.5)
            shap_row = explainer.shap_values(X)
            if isinstance(shap_row, list):
                shap_row = shap_row[1]
            shap_row = shap_row[0]

            save_ml_prediction(db, company.id, {
                "model_name": "earnings_surprise_predictor",
                "prediction": safe_float(pred),
                "confidence": safe_float(proba),
                "shap_values": {
                    col: safe_float(v) for col, v in zip(FEATURE_COLS, shap_row)
                },
                "features_used": {
                    col: safe_float(features[col]) for col in FEATURE_COLS
                },
            })
            saved += 1
        return saved
    finally:
        db.close()


def main():
    print("Loading earnings dataset from PostgreSQL...")
    df = load_earnings_dataset()
    print(
        f"  built {len(df)} (company, quarter) rows across "
        f"{df['ticker'].nunique() if not df.empty else 0} tickers"
    )

    if df.empty:
        print("No usable earnings rows. Run the ingestion pipeline first.")
        return

    train, test = split_train_test(df)
    print(f"  train: {len(train)} rows  |  test (>= {TEST_QUARTER_CUTOFF}): {len(test)} rows")

    if train.empty:
        print("No training rows before the cutoff. Aborting.")
        return

    print("Training XGBoost classifier...")
    model, metrics, shap_values = train_and_evaluate(train, test)
    if metrics:
        print(f"  test metrics: {metrics}")
    else:
        print("  test set empty -- skipping metrics")

    print("Logging run to MLflow...")
    log_to_mlflow(model, metrics, shap_values, train[FEATURE_COLS])

    print("Generating per-company predictions...")
    saved = predict_and_persist(model)

    print(f"\n{'='*50}")
    print(f"Earnings Surprise Predictor")
    print(f"{'='*50}")
    print(f"  training rows:      {len(train)}")
    print(f"  test rows:          {len(test)}")
    for k, v in metrics.items():
        print(f"  {k:18s} {v:.4f}")
    print(f"  predictions saved:  {saved}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
