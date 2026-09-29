"""
Map latest ml_predictions rows into the structured payloads the frontend
renders (forecast / peer cards + ReportCard signal badges).

Older model runs stored a different shap_values shape than the current
writers emit. These helpers normalize both so the UI never depends on
regex over LLM prose.
"""
from __future__ import annotations

from typing import Any

from backend.db.models import MLPrediction

# Keep in lockstep with backend/ml/*.py model_name strings.
MODEL_ANOMALY = "anomaly_detector"
MODEL_BENEISH = "beneish_m_score"
MODEL_EARNINGS = "earnings_surprise_predictor"
MODEL_SENTIMENT = "finbert_sentiment"
MODEL_FORECAST = "revenue_forecaster"
MODEL_PEERS = "peer_clustering"

_BENEISH_LABELS = {"clean", "grey_area", "manipulator"}


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_forecast(
    shap_values: dict | None,
    prediction: Any = None,
) -> dict | None:
    """Return a ForecastSignal-shaped dict, or None if nothing usable."""
    sv = dict(shap_values) if isinstance(shap_values, dict) else {}
    if sv.get("status") == "insufficient_data":
        return sv

    out = dict(sv)

    if out.get("forecast_next_q") is None and out.get("forecast_revenue") is not None:
        out["forecast_next_q"] = out["forecast_revenue"]
    if out.get("forecast_next_q") is None:
        pred = _as_float(prediction)
        if pred is not None:
            out["forecast_next_q"] = pred

    if out.get("forecast_low") is None and out.get("lower_bound") is not None:
        out["forecast_low"] = out["lower_bound"]
    if out.get("forecast_high") is None and out.get("upper_bound") is not None:
        out["forecast_high"] = out["upper_bound"]

    if out.get("periods_used") is None and out.get("quarters_used") is not None:
        out["periods_used"] = out["quarters_used"]

    if out.get("trend_direction") not in ("up", "down", "flat"):
        growth = _as_float(out.get("median_growth_rate"))
        if growth is None:
            out["trend_direction"] = "flat"
        elif growth > 0.01:
            out["trend_direction"] = "up"
        elif growth < -0.01:
            out["trend_direction"] = "down"
        else:
            out["trend_direction"] = "flat"

    if out.get("forecast_next_q") is None and out.get("status") != "insufficient_data":
        # Empty / feature-only blob — nothing for the card to show.
        if not any(k in out for k in ("forecast_revenue", "quarters_available")):
            return None

    return out or None


def normalize_peers(
    shap_values: dict | None,
    prediction: Any = None,
    confidence: Any = None,
) -> dict | None:
    """Return a PeerSignal-shaped dict. Old rows only store features in
    shap_values and the cluster id on prediction — surface that id."""
    sv = shap_values if isinstance(shap_values, dict) else {}
    out: dict[str, Any] = {}

    for key in ("cluster_id", "cluster_size", "peer_tickers", "cluster_label", "silhouette"):
        if key in sv and sv[key] is not None:
            out[key] = sv[key]

    if out.get("cluster_id") is None:
        cid = _as_int(prediction)
        if cid is not None:
            out["cluster_id"] = cid

    if out.get("silhouette") is None:
        sil = _as_float(confidence)
        if sil is not None:
            out["silhouette"] = sil

    return out or None


def _sentiment_label(score: float | None, shap: dict) -> str | None:
    if score is not None:
        if score > 0.05:
            return "positive"
        if score < -0.05:
            return "negative"
        return "neutral"
    pos = shap.get("positive_count")
    neg = shap.get("negative_count")
    neu = shap.get("neutral_count")
    if pos is None and neg is None and neu is None:
        return None
    counts = {
        "positive": int(pos or 0),
        "negative": int(neg or 0),
        "neutral": int(neu or 0),
    }
    return max(counts, key=counts.get)


def _anomaly_signal(pred: MLPrediction) -> dict:
    score = _as_float(pred.prediction)
    conf = _as_float(pred.confidence)
    flagged = bool(conf is not None and conf >= 1.0)
    return {
        "flagged": flagged,
        "score": score,
        "label": "flagged" if flagged else "clean",
    }


def _beneish_signal(pred: MLPrediction) -> dict:
    features = pred.features_used if isinstance(pred.features_used, dict) else {}
    label = features.get("label")
    if label not in _BENEISH_LABELS:
        # Fall back from confidence bands used when persisting.
        conf = _as_float(pred.confidence)
        if conf is None:
            label = None
        elif conf >= 1.0:
            label = "manipulator"
        elif conf >= 0.5:
            label = "grey_area"
        else:
            label = "clean"
    return {
        "label": label,
        "score": _as_float(pred.prediction),
    }


def _earnings_signal(pred: MLPrediction) -> dict:
    value = _as_float(pred.prediction)
    beat = None if value is None else bool(value >= 0.5)
    return {
        "beat": beat,
        "confidence": _as_float(pred.confidence),
        "label": None if beat is None else ("beat" if beat else "miss"),
    }


def _sentiment_signal(pred: MLPrediction) -> dict:
    shap = pred.shap_values if isinstance(pred.shap_values, dict) else {}
    score = _as_float(pred.prediction)
    if score is None:
        score = _as_float(shap.get("avg_sentiment"))
    return {
        "score": score,
        "label": _sentiment_label(score, shap),
    }


_SIGNAL_BUILDERS = {
    MODEL_ANOMALY: ("anomaly", _anomaly_signal),
    MODEL_BENEISH: ("beneish", _beneish_signal),
    MODEL_EARNINGS: ("earnings", _earnings_signal),
    MODEL_SENTIMENT: ("sentiment", _sentiment_signal),
}


def build_ml_signals(predictions: list[MLPrediction]) -> dict[str, dict | None]:
    """Latest-per-model structured badge payloads. Missing models → None."""
    latest: dict[str, MLPrediction] = {}
    for p in predictions:
        if p.model_name not in latest:
            latest[p.model_name] = p

    out: dict[str, dict | None] = {
        "anomaly": None,
        "beneish": None,
        "earnings": None,
        "sentiment": None,
    }
    for model_name, (key, builder) in _SIGNAL_BUILDERS.items():
        pred = latest.get(model_name)
        if pred is not None:
            out[key] = builder(pred)
    return out


def latest_prediction(
    predictions: list[MLPrediction],
    model_name: str,
) -> MLPrediction | None:
    for p in predictions:
        if p.model_name == model_name:
            return p
    return None
