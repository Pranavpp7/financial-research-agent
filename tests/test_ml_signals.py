"""Tests for structured ML signal / forecast / peer normalization."""
from types import SimpleNamespace

import pytest

from backend.api.ml_signals import (
    build_ml_signals,
    normalize_forecast,
    normalize_peers,
)


def _pred(**kwargs):
    defaults = {
        "model_name": "anomaly_detector",
        "prediction": 0.0,
        "confidence": 0.0,
        "shap_values": {},
        "features_used": {},
        "run_date": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_normalize_forecast_maps_old_shap_keys():
    out = normalize_forecast(
        {
            "forecast_quarter": "2026-Q2",
            "forecast_revenue": 81_417_537_259.0,
            "lower_bound": 75_0,
            "upper_bound": 87_0,
            "median_growth_rate": 0.19,
            "quarters_used": 4,
        },
        prediction=81_417_537_259.0,
    )
    assert out["forecast_next_q"] == pytest.approx(81_417_537_259.0)
    assert out["forecast_low"] == 75_0
    assert out["forecast_high"] == 87_0
    assert out["periods_used"] == 4
    assert out["trend_direction"] == "up"


def test_normalize_forecast_uses_prediction_when_shap_empty_of_value():
    out = normalize_forecast({}, prediction=1.5e9)
    assert out["forecast_next_q"] == pytest.approx(1.5e9)
    assert out["trend_direction"] == "flat"


def test_normalize_forecast_insufficient_data_passthrough():
    sv = {"status": "insufficient_data", "quarters_available": 1, "quarters_required": 4}
    assert normalize_forecast(sv) == sv


def test_normalize_peers_old_schema_uses_prediction_as_cluster_id():
    out = normalize_peers(
        {
            "operating_margin": 0.65,
            "log_revenue": 24.9,
            "beat_rate": 0.85,
        },
        prediction=1.0,
        confidence=0.39,
    )
    assert out["cluster_id"] == 1
    assert out["silhouette"] == pytest.approx(0.39)
    assert "operating_margin" not in out
    assert out.get("cluster_label") is None


def test_normalize_peers_new_schema_preserved():
    sv = {
        "cluster_id": 2,
        "cluster_size": 5,
        "peer_tickers": ["AVGO", "AMD"],
        "cluster_label": "high-margin growth",
        "silhouette": 0.55,
    }
    out = normalize_peers(sv, prediction=9.0, confidence=0.1)
    assert out["cluster_id"] == 2
    assert out["peer_tickers"] == ["AVGO", "AMD"]
    assert out["cluster_label"] == "high-margin growth"
    assert out["silhouette"] == 0.55


def test_build_ml_signals_badge_labels():
    rows = [
        _pred(
            model_name="anomaly_detector",
            prediction=-0.2,
            confidence=0.0,  # clean
        ),
        _pred(
            model_name="beneish_m_score",
            prediction=-2.3,
            confidence=0.0,
            features_used={"label": "clean"},
        ),
        _pred(
            model_name="earnings_surprise_predictor",
            prediction=1.0,
            confidence=0.71,
        ),
        _pred(
            model_name="finbert_sentiment",
            prediction=0.33,
            shap_values={"positive_count": 8, "negative_count": 2, "neutral_count": 5},
        ),
    ]
    signals = build_ml_signals(rows)
    assert signals["anomaly"]["label"] == "clean"
    assert signals["anomaly"]["flagged"] is False
    assert signals["beneish"]["label"] == "clean"
    assert signals["earnings"]["label"] == "beat"
    assert signals["sentiment"]["label"] == "positive"


def test_build_ml_signals_negation_safe_anomaly_and_beneish():
    """Regression: prose like 'did not flag' / 'below manipulation' must not
    affect badges — only structured fields do."""
    rows = [
        _pred(model_name="anomaly_detector", prediction=0.15, confidence=0.0),
        _pred(
            model_name="beneish_m_score",
            prediction=-2.4,
            confidence=0.0,
            features_used={"label": "clean"},
        ),
    ]
    signals = build_ml_signals(rows)
    assert signals["anomaly"]["label"] == "clean"
    assert signals["beneish"]["label"] == "clean"
    assert signals["earnings"] is None
    assert signals["sentiment"] is None


def test_build_ml_signals_flagged_and_manipulator():
    rows = [
        _pred(model_name="anomaly_detector", prediction=-0.5, confidence=1.0),
        _pred(
            model_name="beneish_m_score",
            prediction=-1.0,
            confidence=1.0,
            features_used={"label": "manipulator"},
        ),
        _pred(model_name="earnings_surprise_predictor", prediction=0.0, confidence=0.4),
        _pred(model_name="finbert_sentiment", prediction=-0.2),
    ]
    signals = build_ml_signals(rows)
    assert signals["anomaly"]["label"] == "flagged"
    assert signals["beneish"]["label"] == "manipulator"
    assert signals["earnings"]["label"] == "miss"
    assert signals["sentiment"]["label"] == "negative"


def test_build_ml_signals_uses_latest_row_only():
    older = _pred(
        model_name="anomaly_detector",
        prediction=-0.9,
        confidence=1.0,
    )
    newer = _pred(
        model_name="anomaly_detector",
        prediction=0.1,
        confidence=0.0,
    )
    # Caller passes run_date-desc ordered list (latest first).
    signals = build_ml_signals([newer, older])
    assert signals["anomaly"]["label"] == "clean"
