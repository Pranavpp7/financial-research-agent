"""
Unit tests for the earnings-surprise feature engineering.

These cover the core guarantees the model depends on: features are a pure
function of the PRIOR-quarter history passed in (the no-leakage contract is
enforced by the caller slicing `history[:i]`), the cold-start / partial-data
sentinels fire at the right boundaries, and the time-based split is correct.
No database or network access is required.
"""
import pandas as pd
import pytest

from backend.ml.earnings_predictor import (
    FEATURE_COLS,
    _surprise_pct,
    compute_features,
    split_train_test,
)


def _row(surprise, actual, estimate):
    return {
        "surprise_pct": surprise,
        "eps_actual": actual,
        "eps_estimate": estimate,
    }


def test_compute_features_full_history_increasing_beats():
    history = [
        _row(1.0, 1.1, 1.0),
        _row(2.0, 1.2, 1.0),
        _row(3.0, 1.3, 1.0),
        _row(4.0, 1.4, 1.0),
    ]
    f = compute_features(history)

    assert f["avg_surprise_all"] == 2.5
    assert f["avg_surprise_3q"] == 3.0
    # trend = mean(last 2) - mean(prior 2) = 3.5 - 1.5
    assert f["surprise_trend"] == 2.0
    assert f["beat_rate"] == 1.0
    assert f["consecutive_beats"] == 4
    assert f["estimate_accuracy"] == pytest.approx(0.25)
    assert "_partial_features" not in f


def test_consecutive_beats_counts_only_trailing_streak():
    history = [
        _row(1.0, 1.1, 1.0),   # beat
        _row(-1.0, 0.9, 1.0),  # miss -> breaks streak
        _row(1.0, 1.1, 1.0),   # beat
        _row(1.0, 1.2, 1.0),   # beat
    ]
    f = compute_features(history)
    assert f["consecutive_beats"] == 2
    assert f["beat_rate"] == 0.75


def test_surprise_trend_requires_four_observations():
    # Three surprises: trend is undefined and must stay None, but the row is
    # NOT partial (>= 2 observations), so the other features are populated.
    history = [_row(1.0, 1.1, 1.0), _row(2.0, 1.2, 1.0), _row(3.0, 1.3, 1.0)]
    f = compute_features(history)
    assert f["surprise_trend"] is None
    assert f["avg_surprise_all"] == 2.0
    assert "_partial_features" not in f


def test_single_observation_is_flagged_partial_and_backfilled():
    f = compute_features([_row(1.0, 1.1, 1.0)])
    assert f["_partial_features"] is True
    # Hard-minimum feature backfilled to 0.0 rather than left None.
    assert f["surprise_trend"] == 0.0
    assert all(f[c] is not None for c in FEATURE_COLS)


def test_empty_history_yields_no_signal():
    f = compute_features([])
    assert f["avg_surprise_all"] is None
    assert f["surprise_trend"] is None
    assert f["consecutive_beats"] == 0
    assert "_partial_features" not in f


def test_compute_features_does_not_mutate_input():
    history = [_row(1.0, 1.1, 1.0), _row(2.0, 1.2, 1.0)]
    snapshot = [dict(r) for r in history]
    compute_features(history)
    assert history == snapshot


def test_surprise_pct_formula_and_guards():
    assert _surprise_pct(1.2, 1.0) == pytest.approx(20.0)
    assert _surprise_pct(0.8, 1.0) == pytest.approx(-20.0)
    assert _surprise_pct(1.0, 0) is None      # divide-by-zero guard
    assert _surprise_pct(None, 1.0) is None
    assert _surprise_pct(1.0, None) is None


def test_split_train_test_is_time_based():
    df = pd.DataFrame(
        {
            "quarter": ["2024-Q4", "2025-Q3", "2025-Q4", "2026-Q1"],
            "beat": [0, 1, 0, 1],
        }
    )
    train, test = split_train_test(df, cutoff="2025-Q4")
    assert list(train["quarter"]) == ["2024-Q4", "2025-Q3"]
    assert list(test["quarter"]) == ["2025-Q4", "2026-Q1"]
