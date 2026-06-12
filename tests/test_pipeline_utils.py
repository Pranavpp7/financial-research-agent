"""Unit tests for ingestion utility functions (pure, no I/O)."""
import pytest

from backend.ingestion.pipeline import date_to_quarter, safe_float


@pytest.mark.parametrize(
    "value, expected",
    [
        (1.5, 1.5),
        ("1.5", 1.5),
        (0, 0.0),
        (None, None),
        ("nan", None),
        ("not-a-number", None),
    ],
)
def test_safe_float(value, expected):
    assert safe_float(value) == expected


@pytest.mark.parametrize(
    "date_str, expected",
    [
        ("2026-01-15", "2026-Q1"),
        ("2026-04-30", "2026-Q2"),
        ("2026-09-01", "2026-Q3"),
        ("2026-12-31", "2026-Q4"),
        ("2026-04-30T00:00:00Z", "2026-Q2"),  # timestamp is truncated to date
    ],
)
def test_date_to_quarter_valid(date_str, expected):
    assert date_to_quarter(date_str) == expected


@pytest.mark.parametrize("bad", ["", None, "garbage", "2026/04/30"])
def test_date_to_quarter_invalid_returns_none(bad):
    assert date_to_quarter(bad) is None
