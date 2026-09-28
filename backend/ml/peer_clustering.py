"""
Peer Clustering.

Groups companies by financial similarity using KMeans (n_clusters=5,
persisted to ml_predictions) and runs DBSCAN as an exploratory check
for natural clusters. Per-company silhouette scores are stored as
the prediction confidence.
"""
import numpy as np
import pandas as pd
import mlflow
import mlflow.sklearn
import structlog
from dotenv import load_dotenv
from sklearn.cluster import DBSCAN, KMeans
from sklearn.metrics import silhouette_samples, silhouette_score
from sklearn.preprocessing import StandardScaler

from backend.db.session import SessionLocal
from backend.db.models import Company, Earning
from backend.db.crud import save_ml_prediction
from backend.ingestion.pipeline import safe_float

load_dotenv()

logger = structlog.get_logger(__name__)

PEER_TICKERS_LIMIT = 5


def _cluster_label(cluster_means: dict, global_medians: dict) -> str:
    """
    Heuristic human-readable label for a cluster, derived by comparing the
    cluster's mean feature values to the dataset-wide medians. Best-effort:
    intended for analyst context, not a rigorous taxonomy.
    """
    parts = []
    if cluster_means["log_revenue"] >= global_medians["log_revenue"]:
        parts.append("large-cap")
    else:
        parts.append("small/mid-cap")
    if cluster_means["operating_margin"] >= global_medians["operating_margin"]:
        parts.append("high-margin")
    if (
        cluster_means["avg_surprise_pct"] >= global_medians["avg_surprise_pct"]
        and cluster_means["beat_rate"] >= global_medians["beat_rate"]
    ):
        parts.append("high-growth")
    elif cluster_means["beat_rate"] < global_medians["beat_rate"]:
        parts.append("steady/value")
    return " ".join(parts) if parts else "mixed"


FEATURE_COLS = [
    "operating_margin",
    "log_revenue",
    "avg_surprise_pct",
    "eps_actual_latest",
    "beat_rate",
]

N_CLUSTERS = 5
RANDOM_STATE = 42

# DBSCAN runs on standardized features, so eps is in std-deviation units.
# 0.8 / min_samples=3 are sensible starting points for ~10s-100s of points.
DBSCAN_EPS = 0.8
DBSCAN_MIN_SAMPLES = 3


def build_company_features() -> pd.DataFrame:
    """One row per company with the 5 clustering features."""
    db = SessionLocal()
    try:
        rows = []
        for company in db.query(Company).all():
            earnings = (
                db.query(Earning)
                .filter(Earning.company_id == company.id)
                .order_by(Earning.report_date.desc())
                .all()
            )
            if not earnings:
                continue

            latest = earnings[0]

            surprises = [
                e.surprise_pct for e in earnings if e.surprise_pct is not None
            ]
            avg_surprise = float(np.mean(surprises)) if surprises else None

            beats = [
                1 if e.eps_actual > e.eps_estimate else 0
                for e in earnings
                if e.eps_actual is not None and e.eps_estimate is not None
            ]
            beat_rate = float(np.mean(beats)) if beats else None

            log_revenue = (
                float(np.log1p(latest.revenue))
                if latest.revenue is not None and latest.revenue > 0
                else None
            )

            row = {
                "company_id": company.id,
                "ticker": company.ticker,
                "sector": company.sector,
                "revenue_raw": latest.revenue,
                "operating_margin": latest.operating_margin,
                "log_revenue": log_revenue,
                "avg_surprise_pct": avg_surprise,
                "eps_actual_latest": latest.eps_actual,
                "beat_rate": beat_rate,
            }
            if any(row[c] is None for c in FEATURE_COLS):
                continue
            rows.append(row)
        return pd.DataFrame(rows)
    finally:
        db.close()


def main():
    print("Loading per-company features from PostgreSQL...")
    df = build_company_features()
    print(f"  {len(df)} companies have all 5 features populated")

    if len(df) < N_CLUSTERS:
        print(
            f"Need at least {N_CLUSTERS} companies to fit "
            f"KMeans(n_clusters={N_CLUSTERS}). Run the ingestion pipeline first."
        )
        return

    X = df[FEATURE_COLS].astype(float).to_numpy()

    print("Standardizing features...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # ── KMeans (primary, persisted) ──────────────────
    print(f"Fitting KMeans (n_clusters={N_CLUSTERS})...")
    kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=RANDOM_STATE, n_init=10)
    kmeans_labels = kmeans.fit_predict(X_scaled)
    df["kmeans_cluster"] = kmeans_labels

    if len(set(kmeans_labels)) > 1:
        sample_sil = silhouette_samples(X_scaled, kmeans_labels)
        overall_sil = float(silhouette_score(X_scaled, kmeans_labels))
    else:
        sample_sil = np.zeros(len(df))
        overall_sil = 0.0
    df["silhouette"] = sample_sil

    # ── DBSCAN (exploratory only) ───────────────────
    print(f"Fitting DBSCAN (eps={DBSCAN_EPS}, min_samples={DBSCAN_MIN_SAMPLES})...")
    dbscan = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES)
    dbscan_labels = dbscan.fit_predict(X_scaled)
    df["dbscan_cluster"] = dbscan_labels
    n_dbscan_clusters = len(set(dbscan_labels)) - (1 if -1 in dbscan_labels else 0)
    n_noise = int((dbscan_labels == -1).sum())

    # ── MLflow ──────────────────────────────────────
    print("Logging run to MLflow...")
    mlflow.set_experiment("peer_clustering")
    with mlflow.start_run():
        mlflow.log_params({
            "n_clusters_kmeans": N_CLUSTERS,
            "random_state": RANDOM_STATE,
            "dbscan_eps": DBSCAN_EPS,
            "dbscan_min_samples": DBSCAN_MIN_SAMPLES,
            "features": ",".join(FEATURE_COLS),
        })
        mlflow.log_metric("companies_clustered", len(df))
        mlflow.log_metric("kmeans_silhouette_overall", overall_sil)
        mlflow.log_metric("dbscan_clusters", n_dbscan_clusters)
        mlflow.log_metric("dbscan_noise_points", n_noise)
        mlflow.sklearn.log_model(kmeans, "kmeans")

    # ── Precompute per-cluster stats for shap_values enrichment ──
    global_medians = {col: float(df[col].median()) for col in FEATURE_COLS}
    cluster_sizes = df.groupby("kmeans_cluster").size().to_dict()
    cluster_tickers = (
        df.groupby("kmeans_cluster")["ticker"].apply(list).to_dict()
    )
    cluster_label_by_id = {}
    for cid in df["kmeans_cluster"].unique():
        members = df[df["kmeans_cluster"] == cid]
        cluster_means = {col: float(members[col].mean()) for col in FEATURE_COLS}
        cluster_label_by_id[int(cid)] = _cluster_label(cluster_means, global_medians)

    # ── Persist KMeans assignments ──────────────────
    print("Persisting KMeans cluster assignments to ml_predictions...")
    db = SessionLocal()
    saved = 0
    try:
        for _, row in df.iterrows():
            cid = int(row["kmeans_cluster"])
            feature_values = {col: safe_float(row[col]) for col in FEATURE_COLS}
            # Up to N same-cluster peers, excluding the company itself.
            peers = [t for t in cluster_tickers.get(cid, []) if t != row["ticker"]]
            save_ml_prediction(db, int(row["company_id"]), {
                "model_name": "peer_clustering",
                "prediction": float(cid),
                "confidence": safe_float(row["silhouette"]),
                "shap_values": {
                    "cluster_id": cid,
                    "cluster_size": int(cluster_sizes.get(cid, 0)),
                    "peer_tickers": peers[:PEER_TICKERS_LIMIT],
                    "cluster_label": cluster_label_by_id.get(cid, "mixed"),
                    # Additive: surface the fit score so the frontend can
                    # render a silhouette progress bar (also stored as the
                    # row's confidence).
                    "silhouette": safe_float(row["silhouette"]),
                },
                "features_used": feature_values,
            })
            saved += 1
    finally:
        db.close()

    # ── Summary ─────────────────────────────────────
    print(f"\n{'='*78}")
    print(f"Peer Clustering -- KMeans (n_clusters={N_CLUSTERS})")
    print(f"{'='*78}")
    print(f"  Companies clustered:   {len(df)}")
    print(f"  Predictions saved:     {saved}")
    print(
        f"  Overall silhouette:    {overall_sil:+.4f}  "
        f"(range: -1 to +1, higher = tighter clusters)"
    )
    print()

    for cid in sorted(df["kmeans_cluster"].unique()):
        members = df[df["kmeans_cluster"] == cid]
        avg_margin = members["operating_margin"].mean()
        avg_rev = members["revenue_raw"].mean()
        avg_surprise = members["avg_surprise_pct"].mean()
        avg_beat = members["beat_rate"].mean()
        avg_sil = members["silhouette"].mean()

        print(f"  Cluster {cid}  ({len(members)} companies, avg silhouette {avg_sil:+.3f}):")
        print(
            f"    avg op_margin: {avg_margin:+.4f}    "
            f"avg revenue: ${avg_rev:>15,.0f}"
        )
        print(
            f"    avg surprise:  {avg_surprise:+.2f}%   "
            f"avg beat rate: {avg_beat:.2%}"
        )
        tickers = ", ".join(members.sort_values("ticker")["ticker"].tolist())
        print(f"    tickers: {tickers}")
        print()

    print(
        f"  DBSCAN (exploratory, not persisted): "
        f"{n_dbscan_clusters} natural cluster(s), {n_noise} noise point(s)"
    )
    for cid in sorted(c for c in df["dbscan_cluster"].unique() if c != -1):
        members = df[df["dbscan_cluster"] == cid]
        tickers = ", ".join(members.sort_values("ticker")["ticker"].tolist())
        print(f"    DBSCAN cluster {cid}: {tickers}")
    if n_noise > 0:
        noise_tickers = ", ".join(
            df[df["dbscan_cluster"] == -1].sort_values("ticker")["ticker"].tolist()
        )
        print(f"    DBSCAN noise:      {noise_tickers}")
    print(f"{'='*78}\n")


if __name__ == "__main__":
    main()
