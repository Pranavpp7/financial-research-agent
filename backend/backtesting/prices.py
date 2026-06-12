"""
Historical price lookup via yfinance.

Caches results in a module-level dict to avoid hitting the yfinance API
repeatedly during a backtest run. All network access is wrapped in
try/except with structured logging; failures return None.
"""
from datetime import date, datetime, timedelta
from typing import Optional, Union

import structlog

logger = structlog.get_logger(__name__)

# (ticker, isodate) -> close price (or None if unavailable)
_price_cache: dict[tuple[str, str], Optional[float]] = {}


def _as_date(d: Union[date, datetime]) -> date:
    return d.date() if isinstance(d, datetime) else d


def get_price_on(ticker: str, when: Union[date, datetime]) -> Optional[float]:
    """
    Close price on `when`. If markets were closed (weekend/holiday), use the
    next available trading day's close within a 6-day window. Cached.
    """
    day = _as_date(when)
    cache_key = (ticker.upper(), day.isoformat())
    if cache_key in _price_cache:
        return _price_cache[cache_key]

    try:
        import yfinance as yf

        # Fetch a small window starting at `day` to find the next trading day.
        start = day
        end = day + timedelta(days=7)
        hist = yf.Ticker(ticker).history(
            start=start.isoformat(), end=end.isoformat(), auto_adjust=True
        )
        if hist is None or hist.empty:
            _price_cache[cache_key] = None
            return None
        close = float(hist["Close"].iloc[0])
        _price_cache[cache_key] = close
        return close
    except Exception as e:
        logger.error("price_lookup_failed", ticker=ticker, date=day.isoformat(), error=str(e))
        _price_cache[cache_key] = None
        return None


def get_forward_return(
    ticker: str, entry_date: Union[date, datetime], days: int
) -> Optional[float]:
    """(price_after_N_days - price_at_entry) / price_at_entry, or None."""
    entry = get_price_on(ticker, entry_date)
    if entry is None or entry == 0:
        return None
    exit_price = get_price_on(ticker, _as_date(entry_date) + timedelta(days=days))
    if exit_price is None:
        return None
    return (exit_price - entry) / entry
