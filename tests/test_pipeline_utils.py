"""Unit tests for ingestion utility functions (pure, no I/O)."""
import pytest

from backend.ingestion.pipeline import (
    date_to_quarter,
    fiscal_quarter_for_announcement,
    previous_calendar_quarter,
    quarter_period_end,
    safe_float,
)


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


@pytest.mark.parametrize(
    "quarter, expected",
    [
        ("2024-Q1", "2024-03-31"),
        ("2024-Q2", "2024-06-30"),
        ("2024-Q3", "2024-09-30"),
        ("2024-Q4", "2024-12-31"),
        ("2023-Q4", "2023-12-31"),
    ],
)
def test_quarter_period_end(quarter, expected):
    assert quarter_period_end(quarter).strftime("%Y-%m-%d") == expected


@pytest.mark.parametrize(
    "quarter, expected",
    [
        ("2024-Q1", "2023-Q4"),
        ("2024-Q2", "2024-Q1"),
        ("2024-Q3", "2024-Q2"),
        ("2024-Q4", "2024-Q3"),
    ],
)
def test_previous_calendar_quarter(quarter, expected):
    assert previous_calendar_quarter(quarter) == expected


def test_fiscal_quarter_matches_period_end_not_announcement_quarter():
    # Announced mid-Q2 for the just-ended Q1 fiscal period.
    available = {"2024-Q1", "2023-Q4", "2023-Q3", "2023-Q2"}
    assert (
        fiscal_quarter_for_announcement("2024-04-25", available_quarters=available)
        == "2024-Q1"
    )


def test_fiscal_quarter_picks_latest_ended_period():
    available = {"2024-Q1", "2024-Q2", "2023-Q4"}
    # Mid-July announcement after Q2 end → Q2, not Q1.
    assert (
        fiscal_quarter_for_announcement("2024-07-20", available_quarters=available)
        == "2024-Q2"
    )


def test_fiscal_quarter_fallback_without_ratios():
    # No ratio quarters: shift announcement calendar quarter back one.
    assert fiscal_quarter_for_announcement("2024-04-25") == "2024-Q1"
    assert fiscal_quarter_for_announcement("2024-01-15") == "2023-Q4"


@pytest.mark.parametrize("bad", ["", None, "garbage"])
def test_fiscal_quarter_invalid_returns_none(bad):
    assert fiscal_quarter_for_announcement(bad) is None
