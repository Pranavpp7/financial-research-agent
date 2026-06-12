"""
Unit tests for the Beneish M-Score math.

The model is a deterministic linear formula over 8 ratios, so it is fully
testable without a database. We pin the exact ratios we can compute from the
persisted columns (SGI from revenue, GMI approximated from operating margin),
the neutral defaults for the rest, and the classification thresholds.
"""
import pytest

from backend.ml.beneish_score import (
    NEUTRAL_INDEX,
    NEUTRAL_TATA,
    classify,
    compute_ratios,
    confidence_for,
    m_score,
)


def _neutral_ratios():
    return {
        "DSRI": NEUTRAL_INDEX, "GMI": NEUTRAL_INDEX, "AQI": NEUTRAL_INDEX,
        "SGI": NEUTRAL_INDEX, "DEPI": NEUTRAL_INDEX, "SGAI": NEUTRAL_INDEX,
        "TATA": NEUTRAL_TATA, "LVGI": NEUTRAL_INDEX,
    }


def test_compute_ratios_sgi_from_revenue():
    ratios = compute_ratios({"revenue": 110.0}, {"revenue": 100.0})
    assert ratios["SGI"] == pytest.approx(1.1)


def test_compute_ratios_gmi_from_operating_margin():
    # GMI = margin_{t-1} / margin_t  (compression -> > 1)
    ratios = compute_ratios(
        {"revenue": 100.0, "operating_margin": 0.20},
        {"revenue": 100.0, "operating_margin": 0.25},
    )
    assert ratios["GMI"] == pytest.approx(1.25)


def test_compute_ratios_defaults_when_data_missing():
    ratios = compute_ratios({}, {})
    assert ratios["SGI"] == NEUTRAL_INDEX
    assert ratios["GMI"] == NEUTRAL_INDEX
    assert ratios["TATA"] == NEUTRAL_TATA


def test_compute_ratios_guards_zero_and_none_prior_revenue():
    assert compute_ratios({"revenue": 100.0}, {"revenue": 0})["SGI"] == NEUTRAL_INDEX
    assert compute_ratios({"revenue": 100.0}, {"revenue": None})["SGI"] == NEUTRAL_INDEX


def test_m_score_on_all_neutral_inputs():
    # Closed-form value for the all-neutral baseline.
    assert m_score(_neutral_ratios()) == pytest.approx(-2.38642)


def test_classify_thresholds():
    assert classify(-1.0) == "manipulator"   # > -1.78
    assert classify(-1.78) == "grey_area"     # boundary is exclusive of manipulator
    assert classify(-2.0) == "grey_area"      # in (-2.22, -1.78]
    assert classify(-2.22) == "clean"         # boundary is exclusive of grey
    assert classify(-3.0) == "clean"


def test_confidence_for_mapping():
    assert confidence_for("manipulator") == 1.0
    assert confidence_for("grey_area") == 0.5
    assert confidence_for("clean") == 0.0
