"""
Beneish M-Score.

Statistical formula combining 8 financial ratios to flag potential
earnings manipulation. The full formula needs balance-sheet and
cashflow line items (accounts receivable, PP&E, depreciation, SG&A,
debt, operating cashflow) that this project does not yet persist.
We compute SGI exactly from `revenue` and approximate GMI using
`operating_margin` as a stand-in for `gross_margin`. The remaining
six ratios default to neutral values (1.0 for index ratios, 0.02
for TATA -- a typical US large-cap median accruals ratio).

In practice this means the score is dominated by revenue growth
(SGI) and margin compression (GMI), not true accruals quality.
Treat the output as a heuristic until the underlying line items
are added to the ingestion pipeline.
"""
import pandas as pd
import mlflow
from dotenv import load_dotenv

from backend.db.session import SessionLocal
from backend.db.models import Company, Earning
from backend.db.crud import save_ml_prediction
from backend.ingestion.pipeline import safe_float

load_dotenv()


# Beneish (1999) coefficients
COEFS = {
    "intercept": -4.84,
    "DSRI":  0.920,
    "GMI":   0.528,
    "AQI":   0.404,
    "SGI":   0.892,
    "DEPI":  0.115,
    "SGAI": -0.172,
    "TATA":  4.679,
    "LVGI": -0.327,
}

MANIPULATOR_THRESHOLD = -1.78  # M > this  -> likely manipulator
GREY_THRESHOLD        = -2.22  # M in (-2.22, -1.78] -> grey area

# Neutral defaults for ratios we cannot compute from available data.
# 1.0 means "no year-over-year change" -- the neutral value for any
# index expressed as period_t / period_{t-1}. TATA is an absolute
# accruals ratio; 0.02 is the rough US large-cap median.
NEUTRAL_INDEX = 1.0
NEUTRAL_TATA  = 0.02


def _earning_to_dict(e: Earning) -> dict:
    return {
        "quarter": e.quarter,
        "report_date": e.report_date,
        "revenue": e.revenue,
        "operating_margin": e.operating_margin,
        "net_income": e.net_income,
    }


def compute_ratios(curr: dict, prev: dict) -> dict:
    """
    Compute the 8 Beneish ratios from two consecutive quarters.
    Ratios that depend on un-persisted line items get neutral defaults.
    """
    ratios = {
        "DSRI": NEUTRAL_INDEX,  # needs accounts receivable
        "GMI":  NEUTRAL_INDEX,  # approximated below from operating_margin
        "AQI":  NEUTRAL_INDEX,  # needs current assets + PP&E + total assets
        "SGI":  NEUTRAL_INDEX,  # computed below from revenue
        "DEPI": NEUTRAL_INDEX,  # needs depreciation + PP&E
        "SGAI": NEUTRAL_INDEX,  # needs SG&A expense line
        "TATA": NEUTRAL_TATA,   # needs operating cashflow + total assets
        "LVGI": NEUTRAL_INDEX,  # needs LT debt + current liabilities
    }

    # SGI = revenue_t / revenue_{t-1}  (exact)
    rev_t, rev_p = curr.get("revenue"), prev.get("revenue")
    if rev_t is not None and rev_p not in (None, 0):
        ratios["SGI"] = rev_t / rev_p

    # GMI = gross_margin_{t-1} / gross_margin_t
    # APPROXIMATION: gross_margin not persisted -> use operating_margin.
    # Operating margin = gross margin minus opex; the two are correlated
    # but operating margin is uniformly lower. Direction (compression vs
    # expansion) is preserved, magnitude is overstated.
    om_t, om_p = curr.get("operating_margin"), prev.get("operating_margin")
    if om_t not in (None, 0) and om_p is not None:
        ratios["GMI"] = om_p / om_t

    return ratios


def m_score(ratios: dict) -> float:
    return (
        COEFS["intercept"]
        + COEFS["DSRI"] * ratios["DSRI"]
        + COEFS["GMI"]  * ratios["GMI"]
        + COEFS["AQI"]  * ratios["AQI"]
        + COEFS["SGI"]  * ratios["SGI"]
        + COEFS["DEPI"] * ratios["DEPI"]
        + COEFS["SGAI"] * ratios["SGAI"]
        + COEFS["TATA"] * ratios["TATA"]
        + COEFS["LVGI"] * ratios["LVGI"]
    )


def classify(score: float) -> str:
    if score > MANIPULATOR_THRESHOLD:
        return "manipulator"
    if score > GREY_THRESHOLD:
        return "grey_area"
    return "clean"


def confidence_for(label: str) -> float:
    return {"manipulator": 1.0, "grey_area": 0.5, "clean": 0.0}[label]


def main():
    print("Computing Beneish M-Scores from PostgreSQL earnings data...")

    db = SessionLocal()
    rows = []
    try:
        for company in db.query(Company).all():
            earnings = (
                db.query(Earning)
                .filter(Earning.company_id == company.id)
                .order_by(Earning.report_date.desc())
                .all()
            )
            history = [_earning_to_dict(e) for e in earnings]
            usable = [
                h for h in history
                if h["revenue"] is not None and h["operating_margin"] is not None
            ]
            if len(usable) < 2:
                continue

            curr, prev = usable[0], usable[1]
            ratios = compute_ratios(curr, prev)
            score = m_score(ratios)
            label = classify(score)

            save_ml_prediction(db, company.id, {
                "model_name": "beneish_m_score",
                "prediction": safe_float(score),
                "confidence": confidence_for(label),
                "shap_values": {k: safe_float(v) for k, v in ratios.items()},
                "features_used": {
                    "revenue_t": safe_float(curr["revenue"]),
                    "revenue_t_minus_1": safe_float(prev["revenue"]),
                    "operating_margin_t": safe_float(curr["operating_margin"]),
                    "operating_margin_t_minus_1": safe_float(prev["operating_margin"]),
                    "quarter_t": curr["quarter"],
                    "quarter_t_minus_1": prev["quarter"],
                    "label": label,
                },
            })

            rows.append({
                "ticker": company.ticker,
                "quarter_t": curr["quarter"],
                "quarter_t1": prev["quarter"],
                "score": score,
                "label": label,
                **ratios,
            })
    finally:
        db.close()

    if not rows:
        print(
            "No companies have >= 2 quarters with both revenue and "
            "operating_margin populated. Run the ingestion pipeline first "
            "so financial ratios get merged into earnings rows."
        )
        return

    df = pd.DataFrame(rows).sort_values("score", ascending=False)
    counts = df["label"].value_counts().to_dict()

    print("Logging run to MLflow...")
    mlflow.set_experiment("beneish_m_score")
    with mlflow.start_run():
        for k, v in COEFS.items():
            mlflow.log_param(f"coef_{k}", v)
        mlflow.log_param("manipulator_threshold", MANIPULATOR_THRESHOLD)
        mlflow.log_param("grey_threshold", GREY_THRESHOLD)
        mlflow.log_param("neutral_index_default", NEUTRAL_INDEX)
        mlflow.log_param("neutral_tata_default", NEUTRAL_TATA)
        mlflow.log_metric("companies_scored", len(df))
        mlflow.log_metric("manipulators", counts.get("manipulator", 0))
        mlflow.log_metric("grey_area", counts.get("grey_area", 0))
        mlflow.log_metric("clean", counts.get("clean", 0))
        mlflow.log_metric("score_mean", float(df["score"].mean()))
        mlflow.log_metric("score_max", float(df["score"].max()))
        mlflow.log_metric("score_min", float(df["score"].min()))

    print(f"\n{'='*78}")
    print(f"Beneish M-Score")
    print(f"{'='*78}")
    print(f"  Companies scored: {len(df)}")
    print(f"    manipulator:  {counts.get('manipulator', 0)}  (M > {MANIPULATOR_THRESHOLD})")
    print(f"    grey_area:    {counts.get('grey_area', 0)}  ({GREY_THRESHOLD} < M <= {MANIPULATOR_THRESHOLD})")
    print(f"    clean:        {counts.get('clean', 0)}  (M <= {GREY_THRESHOLD})")
    print()
    print(f"  {'Ticker':<8} {'M-Score':>9}  {'Label':<12} {'SGI':>6} {'GMI':>8}  Quarters")
    print(f"  {'-'*8} {'-'*9}  {'-'*12} {'-'*6} {'-'*8}  {'-'*20}")
    for _, r in df.iterrows():
        print(
            f"  {r['ticker']:<8} {r['score']:>+9.4f}  {r['label']:<12} "
            f"{r['SGI']:>6.3f} {r['GMI']:>+8.3f}  "
            f"{r['quarter_t']} vs {r['quarter_t1']}"
        )
    print(f"{'='*78}\n")

    print(
        "NOTE: 6 of the 8 ratios (DSRI, AQI, DEPI, SGAI, LVGI, TATA) use "
        "neutral defaults because the underlying line items are not "
        "persisted. Scores reflect mainly SGI (revenue growth) and GMI "
        "(operating-margin compression as a gross-margin proxy). For real "
        "M-Scores, persist accounts receivable, PP&E, depreciation, SG&A, "
        "debt, and operating cashflow per quarter."
    )


if __name__ == "__main__":
    main()
