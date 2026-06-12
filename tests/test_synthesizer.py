"""Unit tests for synthesizer helpers that sanitize LLM output."""
import pytest

from backend.agents.synthesizer import _clamp_unit


@pytest.mark.parametrize(
    "value, expected",
    [
        (0.5, 0.5),
        (1.5, 1.0),     # clamped to upper bound
        (-0.2, 0.0),    # clamped to lower bound
        ("0.7", 0.7),   # numeric strings are coerced
        (1, 1.0),
    ],
)
def test_clamp_unit_in_range(value, expected):
    assert _clamp_unit(value) == pytest.approx(expected)


@pytest.mark.parametrize("garbage", [None, "abc", "", [], {}])
def test_clamp_unit_falls_back_on_garbage(garbage):
    assert _clamp_unit(garbage) == 0.0
    assert _clamp_unit(garbage, default=0.5) == 0.5
