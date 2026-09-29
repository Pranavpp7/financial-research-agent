"""
Analyzer: runs one specialized analysis (earnings | sec | news | risk).

Each type has its own data-loading function; the Groq call shape is shared.
The user's question is passed through to all analyses (and used as the
retrieval query for "sec").
"""
import os
from datetime import datetime, timezone

import structlog
from dotenv import load_dotenv
from groq import Groq

from backend.core.groq_config import get_groq_model
from backend.core.rate_limiter import get_rate_limiter
from backend.db.session import SessionLocal
from backend.db.models import Earning, MLPrediction, NewsArticle
from backend.agents.prompts import (
    EARNINGS_PROMPT, FORECAST_PROMPT, NEWS_PROMPT, RISK_PROMPT, SEC_PROMPT,
)
from backend.rag.retriever import search as rag_search

load_dotenv()

logger = structlog.get_logger(__name__)

PROMPTS = {
    "earnings": EARNINGS_PROMPT,
    "sec": SEC_PROMPT,
    "news": NEWS_PROMPT,
    "risk": RISK_PROMPT,
    "forecast": FORECAST_PROMPT,
}

# Single source of truth for the model_name strings that each ML module
# writes to ml_predictions. Keep these in lockstep with backend/ml/*.py:
#   earnings_predictor.py  -> "earnings_surprise_predictor"
#   anomaly_detector.py    -> "anomaly_detector"
#   beneish_score.py       -> "beneish_m_score"
#   sentiment_evaluator.py -> "finbert_sentiment"
#   peer_clustering.py     -> "peer_clustering"
#   revenue_forecaster.py  -> "revenue_forecaster"
ML_MODEL_NAMES = {
    "earnings": "earnings_surprise_predictor",
    "anomaly": "anomaly_detector",
    "beneish": "beneish_m_score",
    "sentiment": "finbert_sentiment",
    "peer_clustering": "peer_clustering",
    "revenue_forecaster": "revenue_forecaster",
}

# Stale-prediction threshold (days) for the age warning.
ML_PREDICTION_MAX_AGE_DAYS = 7

# Ratio name -> rough Beneish (1999) manipulator-mean threshold. A value
# above this leans "elevated"; near the neutral default it carries no signal.
BENEISH_RATIO_THRESHOLDS = {
    "DSRI": 1.465, "GMI": 1.193, "AQI": 1.254, "SGI": 1.607,
    "DEPI": 1.077, "SGAI": 1.041, "TATA": 0.031, "LVGI": 1.111,
}
BENEISH_RATIO_ORDER = ["DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "TATA", "LVGI"]


def _ml_prediction_age_warning(run_date) -> str:
    """
    Return a stale-data warning if `run_date` is older than the threshold,
    else "". DB timestamps are naive UTC (datetime.utcnow), so treat a
    naive value as UTC before comparing.
    """
    if not run_date:
        return ""
    if run_date.tzinfo is None:
        run_date = run_date.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - run_date).days
    if age_days > ML_PREDICTION_MAX_AGE_DAYS:
        return (
            f"⚠ ML predictions are {age_days} days old "
            "— consider re-running models."
        )
    return ""


def _signed(value) -> str:
    """Format a number with an explicit sign and 4 dp; pass non-numbers through."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return f"{value:+.4f}"


def _beneish_ratio_label(name: str, value) -> str:
    """Interpretation label for one Beneish ratio."""
    if value is None or not isinstance(value, (int, float)):
        return "n/a"
    default = 0.02 if name == "TATA" else 1.0
    if abs(value - default) < 1e-9:
        return "[likely default]"
    threshold = BENEISH_RATIO_THRESHOLDS.get(name)
    if threshold is not None and value > threshold:
        return "elevated"
    return "normal"


def _format_earnings_context(db, company_id: int) -> str:
    earnings = (
        db.query(Earning)
        .filter(Earning.company_id == company_id)
        .order_by(Earning.report_date.desc())
        .limit(8)
        .all()
    )
    pred = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.company_id == company_id,
            MLPrediction.model_name == ML_MODEL_NAMES["earnings"],
        )
        .order_by(MLPrediction.run_date.desc())
        .first()
    )

    lines = []
    warning = _ml_prediction_age_warning(pred.run_date) if pred else ""
    if warning:
        lines.append(warning)
        lines.append("")

    # Cold-start sentinel (written by earnings_predictor when a company has
    # fewer than MIN_QUARTERS_REQUIRED quarters): surface the gap up front so
    # the LLM treats the missing ML signal as a data-coverage issue rather
    # than a bearish signal.
    pred_shap = pred.shap_values if (pred and isinstance(pred.shap_values, dict)) else {}
    cold_start = pred_shap.get("status") == "insufficient_data"
    if cold_start:
        lines.append("⚠ EARNINGS MODEL: INSUFFICIENT DATA (cold start)")
        lines.append(
            f"  Only {pred_shap.get('quarters_available')} usable quarter(s) of "
            f"earnings history are on file; the earnings_surprise_predictor "
            f"needs {pred_shap.get('quarters_required')}. No surprise prediction "
            "is available. Treat this as a data-coverage gap for a newly-tracked "
            "company, NOT as a negative signal."
        )
        lines.append("")

    lines.append("EARNINGS HISTORY (most recent first):")
    if not earnings:
        lines.append("  (no earnings rows for this company)")
    for e in earnings:
        lines.append(
            f"  {e.quarter}  est={e.eps_estimate}  actual={e.eps_actual}  "
            f"surprise={e.surprise_pct}%  rev={e.revenue}  "
            f"net_income={e.net_income}  op_margin={e.operating_margin}"
        )

    lines.append("")
    if cold_start:
        lines.append(
            "ML PREDICTION (earnings_surprise_predictor): insufficient data "
            "(see cold-start notice above)"
        )
    elif pred:
        lines.append("ML PREDICTION (earnings_surprise_predictor):")
        lines.append(
            f"  prediction={pred.prediction}  confidence={pred.confidence}"
        )
        shap = pred.shap_values or {}
        feats = pred.features_used or {}
        if shap:
            # One feature per line, sorted by |SHAP| so the top drivers come
            # first, with the model's input value alongside the attribution.
            lines.append(
                "  SHAP drivers (signed; |impact| desc) with input values:"
            )
            for feat, sval in sorted(
                shap.items(), key=lambda kv: abs(kv[1] or 0), reverse=True
            ):
                lines.append(
                    f"    {feat:18s} shap={_signed(sval):>10}  "
                    f"value={_signed(feats.get(feat))}"
                )
        else:
            lines.append("  SHAP values not available")
            if feats:
                lines.append("  features_used:")
                for feat, fval in feats.items():
                    lines.append(f"    {feat:18s} {_signed(fval)}")
    else:
        lines.append("ML PREDICTION (earnings_surprise_predictor): not available")
    return "\n".join(lines)


def _format_sec_context(question: str, ticker: str, k: int = 6) -> str:
    chunks = rag_search(question, k=k, ticker=ticker)
    if not chunks:
        return f"No SEC filing chunks indexed for {ticker} yet."
    blocks = []
    for c in chunks:
        header = f"[{c['ticker']} {c['form_type']} chunk #{c['chunk_index']}]"
        blocks.append(f"{header}\n{c['chunk_text']}")
    return "\n\n".join(blocks)


NEWS_ARTICLE_CAP = 10


def _format_news_context(db, company_id: int) -> str:
    # Pull all scored articles, then rank by |sentiment| so the most extreme
    # (most informative) headlines lead, rather than the most recent.
    articles = (
        db.query(NewsArticle)
        .filter(NewsArticle.company_id == company_id)
        .filter(NewsArticle.sentiment_score.isnot(None))
        .all()
    )
    articles.sort(key=lambda a: abs(a.sentiment_score or 0), reverse=True)

    pred = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.company_id == company_id,
            MLPrediction.model_name == ML_MODEL_NAMES["sentiment"],
        )
        .order_by(MLPrediction.run_date.desc())
        .first()
    )

    lines = []
    warning = _ml_prediction_age_warning(pred.run_date) if pred else ""
    if warning:
        lines.append(warning)
        lines.append("")

    if pred and pred.shap_values:
        lines.append("AGGREGATE SENTIMENT (finbert_sentiment):")
        for k, v in pred.shap_values.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    if not articles:
        lines.append("RECENT ARTICLES: none with sentiment scores")
    else:
        shown = articles[:NEWS_ARTICLE_CAP]
        lines.append(
            f"ARTICLES BY |SENTIMENT| (showing {len(shown)} of {len(articles)}):"
        )
        for a in shown:
            score_str = (
                f"{a.sentiment_score:+.2f}"
                if a.sentiment_score is not None
                else "n/a"
            )
            lines.append(
                f"  [{a.sentiment_label} {score_str}] {a.title} -- {a.source}"
            )
        remaining = len(articles) - len(shown)
        if remaining > 0:
            lines.append(f"  ... {remaining} more articles not shown")
    return "\n".join(lines)


def _format_risk_context(db, company_id: int) -> str:
    beneish = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.company_id == company_id,
            MLPrediction.model_name == ML_MODEL_NAMES["beneish"],
        )
        .order_by(MLPrediction.run_date.desc())
        .first()
    )
    anomaly = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.company_id == company_id,
            MLPrediction.model_name == ML_MODEL_NAMES["anomaly"],
        )
        .order_by(MLPrediction.run_date.desc())
        .first()
    )

    lines = []
    # Warn once, using the freshest of the two risk-model run dates.
    run_dates = [p.run_date for p in (beneish, anomaly) if p and p.run_date]
    warning = _ml_prediction_age_warning(max(run_dates)) if run_dates else ""
    if warning:
        lines.append(warning)
        lines.append("")

    if beneish:
        lines.append("BENEISH M-SCORE:")
        lines.append(
            f"  M-Score: {beneish.prediction}  confidence: {beneish.confidence}"
        )
        ratios = beneish.shap_values or {}
        if ratios:
            lines.append("  Ratios (one per line, with interpretation):")
            # Fixed Beneish order first, then any extras.
            ordered = BENEISH_RATIO_ORDER + [
                k for k in ratios if k not in BENEISH_RATIO_ORDER
            ]
            for name in ordered:
                if name not in ratios:
                    continue
                value = ratios[name]
                lines.append(
                    f"    {name:6s} {_signed(value):>10}  "
                    f"{_beneish_ratio_label(name, value)}"
                )
        if beneish.features_used:
            lines.append(f"  context: {beneish.features_used}")
    else:
        lines.append("BENEISH M-SCORE: not available")

    lines.append("")
    if anomaly:
        flagged = bool(anomaly.confidence and float(anomaly.confidence) >= 1.0)
        lines.append("ANOMALY DETECTOR (IsolationForest):")
        lines.append(
            f"  anomaly_score: {anomaly.prediction}  flagged: {flagged}"
        )
        zscores = anomaly.shap_values or {}
        if zscores:
            # Highest-risk (most extreme) features first.
            lines.append("  feature z-scores (|z| desc):")
            for feat, z in sorted(
                zscores.items(), key=lambda kv: abs(kv[1] or 0), reverse=True
            ):
                lines.append(f"    {feat:22s} {_signed(z)}")
    else:
        lines.append("ANOMALY DETECTOR: not available")
    return "\n".join(lines)


def _format_forecast_context(db, company_id: int) -> str:
    """Format the revenue_forecaster + peer_clustering predictions for the LLM."""
    forecast = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.company_id == company_id,
            MLPrediction.model_name == ML_MODEL_NAMES["revenue_forecaster"],
        )
        .order_by(MLPrediction.run_date.desc())
        .first()
    )
    peers = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.company_id == company_id,
            MLPrediction.model_name == ML_MODEL_NAMES["peer_clustering"],
        )
        .order_by(MLPrediction.run_date.desc())
        .first()
    )

    lines = []
    run_dates = [p.run_date for p in (forecast, peers) if p and p.run_date]
    warning = _ml_prediction_age_warning(max(run_dates)) if run_dates else ""
    if warning:
        lines.append(warning)
        lines.append("")

    # ── Revenue forecast ──
    if forecast:
        sv = forecast.shap_values or {}
        if sv.get("status") == "insufficient_data":
            lines.append("REVENUE FORECAST: INSUFFICIENT DATA")
            lines.append(
                f"  Only {sv.get('quarters_available')} quarter(s) of revenue "
                f"history; the forecaster needs {sv.get('quarters_required')}. "
                "No revenue forecast is available."
            )
        else:
            lines.append("REVENUE FORECAST (revenue_forecaster):")
            lines.append(
                f"  next quarter: {forecast.prediction}  "
                f"confidence: {forecast.confidence}"
            )
            lines.append(f"  forecast_next_q:      {sv.get('forecast_next_q')}")
            lines.append(f"  forecast_2q:          {sv.get('forecast_2q')}")
            lines.append(f"  trend_direction:      {sv.get('trend_direction')}")
            lines.append(f"  seasonality_strength: {sv.get('seasonality_strength')}")
            lines.append(f"  periods_used:         {sv.get('periods_used')}")
    else:
        lines.append("REVENUE FORECAST (revenue_forecaster): not available")

    lines.append("")

    # ── Peer cluster ──
    if peers:
        sv = peers.shap_values or {}
        lines.append("PEER CLUSTER (peer_clustering):")
        lines.append(
            f"  cluster {sv.get('cluster_id')} "
            f"({sv.get('cluster_label')})  size: {sv.get('cluster_size')}"
        )
        peer_tickers = sv.get("peer_tickers") or []
        lines.append(
            f"  peers: {', '.join(peer_tickers) if peer_tickers else '(none)'}"
        )
        lines.append(f"  fit confidence (silhouette): {peers.confidence}")
    else:
        lines.append("PEER CLUSTER (peer_clustering): not available")

    return "\n".join(lines)


class Analyzer:
    def __init__(self, model: str | None = None):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set in .env")
        self.client = Groq(api_key=api_key)
        self.model = model or get_groq_model()

    def analyze(
        self,
        analysis_type: str,
        ticker: str,
        company_id: int,
        question: str,
    ) -> dict:
        if analysis_type not in PROMPTS:
            return {
                "type": analysis_type,
                "text": "",
                "error": f"unknown analysis type: {analysis_type}",
            }

        # Build context per type
        if analysis_type == "sec":
            context = _format_sec_context(question, ticker)
        else:
            db = SessionLocal()
            try:
                if analysis_type == "earnings":
                    context = _format_earnings_context(db, company_id)
                elif analysis_type == "news":
                    context = _format_news_context(db, company_id)
                elif analysis_type == "forecast":
                    context = _format_forecast_context(db, company_id)
                else:  # risk
                    context = _format_risk_context(db, company_id)
            finally:
                db.close()

        logger.info("analysis_start", ticker=ticker, analysis=analysis_type)
        # Acquire OUTSIDE the try: RateLimitExceeded must propagate to the
        # Celery task (which retries with a countdown) — the generic except
        # below would swallow it into an error dict and the retry path would
        # never trigger.
        get_rate_limiter().acquire("groq")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": PROMPTS[analysis_type]},
                    {"role": "user", "content": (
                        f"Question: {question}\n"
                        f"Ticker: {ticker}\n\n"
                        f"Data:\n{context}"
                    )},
                ],
                temperature=0.2,
            )
            text = response.choices[0].message.content
            return {"type": analysis_type, "text": text, "context": context}
        except Exception as e:
            logger.error("analysis_llm_failed", ticker=ticker, analysis=analysis_type, error=str(e))
            return {"type": analysis_type, "text": "", "error": str(e)}
