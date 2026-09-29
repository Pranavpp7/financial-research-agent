import os
from calendar import monthrange
from datetime import datetime
from typing import Iterable, Optional

import structlog
from dotenv import load_dotenv
from backend.db.session import SessionLocal
from backend.db.crud import (
    get_or_create_company,
    save_filing,
    apply_incoming_earnings,
    save_news_article,
    get_company
)
from backend.ingestion.edgar_client import (
    fetch_filing_html,
    get_company_info,
    get_recent_filings,
)
from backend.ingestion.yfinance_client import (
    get_company_overview,
    get_earnings_history,
    get_price_history,
    get_key_financial_ratios,
)
from backend.ingestion.news_client import get_company_news
from backend.core.rate_limiter import get_rate_limiter

load_dotenv()

logger = structlog.get_logger(__name__)


def safe_float(value):
    """Convert numpy floats or any numeric type to plain Python float."""
    try:
        if value is None or str(value) == "nan":
            return None
        return float(value)
    except Exception:
        # FIXED: was a bare `except:` (also caught KeyboardInterrupt/SystemExit).
        # Scoped to Exception; returning None is the intended coercion fallback.
        return None


def date_to_quarter(date_str: str) -> Optional[str]:
    """
    Convert a date string to calendar-quarter format.
    Example: '2026-04-30' → '2026-Q2'
    """
    if not date_str:
        return None
    try:
        date = datetime.strptime(date_str[:10], "%Y-%m-%d")
        quarter = (date.month - 1) // 3 + 1
        return f"{date.year}-Q{quarter}"
    except Exception:
        # FIXED: bare `except:` -> scoped + logged so malformed dates are
        # visible at debug level instead of vanishing silently.
        logger.debug("date_to_quarter failed to parse %r", date_str, exc_info=True)
        return None


def quarter_period_end(quarter: str) -> Optional[datetime]:
    """Return the calendar period-end date for a 'YYYY-Qn' label."""
    if not quarter or "-Q" not in quarter:
        return None
    try:
        year_s, q_s = quarter.split("-Q", 1)
        year, q = int(year_s), int(q_s)
        if q < 1 or q > 4:
            return None
        month = q * 3
        day = monthrange(year, month)[1]
        return datetime(year, month, day)
    except (TypeError, ValueError):
        return None


def previous_calendar_quarter(quarter: str) -> Optional[str]:
    """Shift a 'YYYY-Qn' label back one calendar quarter."""
    end = quarter_period_end(quarter)
    if end is None:
        return None
    q = (end.month - 1) // 3 + 1
    year = end.year
    if q == 1:
        return f"{year - 1}-Q4"
    return f"{year}-Q{q - 1}"


def fiscal_quarter_for_announcement(
    announcement_date: str,
    available_quarters: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """
    Map an earnings *announcement* date to the fiscal quarter it reports.

    yfinance earnings_dates use the announcement date, while income-statement
    ratios are keyed by period-end. Announcements almost always fall in a
    later calendar quarter than the period reported, so joining on
    date_to_quarter(announcement) systematically misses.

    Prefer the latest available period-end quarter that ended on or before
    the announcement. Fall back to the previous calendar quarter.
    """
    if not announcement_date:
        return None
    try:
        ann = datetime.strptime(announcement_date[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        logger.debug(
            "fiscal_quarter_for_announcement failed to parse %r",
            announcement_date,
            exc_info=True,
        )
        return None

    best_q: Optional[str] = None
    best_end: Optional[datetime] = None
    if available_quarters:
        for q in available_quarters:
            end = quarter_period_end(q)
            if end is None:
                continue
            if end.date() <= ann.date() and (best_end is None or end > best_end):
                best_end = end
                best_q = q
    if best_q is not None:
        return best_q

    ann_q = date_to_quarter(announcement_date)
    return previous_calendar_quarter(ann_q) if ann_q else None


def get_cik_for_ticker(ticker: str) -> str:
    """
    Look up a company's CIK number from SEC EDGAR using their ticker search.
    CIK is SEC's unique identifier for each company.
    """
    import requests

    headers = {
        "User-Agent": f"financial-research-agent {os.getenv('USER_EMAIL', 'test@email.com')}"
    }

    try:
        tickers_url = "https://www.sec.gov/files/company_tickers.json"
        response = requests.get(tickers_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        for key, company in data.items():
            if company.get("ticker", "").upper() == ticker.upper():
                cik = str(company["cik_str"]).zfill(10)
                return cik

        return None

    except Exception as e:
        print(f"Could not find CIK for {ticker}: {e}")
        return None


def run_ingestion_pipeline(ticker: str) -> dict:
    """
    Full ingestion pipeline for a company.
    Fetches data from all three sources and stores in PostgreSQL.

    Steps:
    1. Fetch company info from yfinance + EDGAR
    2. Merge and save to companies table
    3. Fetch and save earnings history
    4. Fetch and save SEC filings
    5. Fetch and save news articles
    """
    print(f"\n{'='*50}")
    print(f"Starting ingestion pipeline for: {ticker}")
    print(f"{'='*50}\n")

    db = SessionLocal()
    results = {
        "ticker": ticker,
        "company_id": None,
        "earnings_saved": 0,
        "ratios_matched": 0,
        "filings_saved": 0,
        "filings_fetched": 0,
        "articles_saved": 0,
        "errors": []
    }

    try:
        # ── STEP 1: Fetch company info ──────────────────────
        print("Step 1: Fetching company info...")

        yf_overview = get_company_overview(ticker)
        cik = get_cik_for_ticker(ticker)
        edgar_info = {}
        if cik:
            edgar_info = get_company_info(cik)

        company_data = {
            "name": yf_overview.get("name") or edgar_info.get("name"),
            "sector": yf_overview.get("sector"),
            "industry": yf_overview.get("industry"),
            "exchange": yf_overview.get("exchange") or edgar_info.get("exchange"),
            "cik": edgar_info.get("cik") or cik,
        }

        company = get_or_create_company(db, ticker, company_data)
        results["company_id"] = company.id
        print(f"Company saved: {company.name} (ID: {company.id})\n")

        # ── STEP 2: Fetch and save earnings ─────────────────
        print("Step 2: Fetching earnings history...")

        earnings_history = get_earnings_history(ticker)

        # ── STEP 2b: Fetch quarterly financial ratios ──────
        print("Step 2b: Fetching quarterly financial ratios...")

        financial_ratios = get_key_financial_ratios(ticker)
        ratios_by_quarter = {
            r["quarter"]: r for r in financial_ratios if r.get("quarter")
        }
        print(f"Fetched ratios for {len(ratios_by_quarter)} quarters")

        prepared_earnings: list[dict] = []
        for earning in earnings_history:
            date_str = earning.get("date", "")
            # Announcement date → fiscal period being reported (not announcement quarter).
            quarter = fiscal_quarter_for_announcement(
                date_str, available_quarters=ratios_by_quarter.keys()
            )

            if not quarter:
                continue

            eps_actual = earning.get("eps_actual")
            if eps_actual is None or str(eps_actual) == "nan":
                continue

            earning_data = {
                "quarter": quarter,
                "date": date_str[:10] if date_str else None,
                "eps_estimate": safe_float(earning.get("eps_estimate")),
                "eps_actual": safe_float(eps_actual),
                "surprise_pct": safe_float(earning.get("surprise_pct")),
            }

            matching_ratio = ratios_by_quarter.get(quarter)
            if matching_ratio:
                earning_data["revenue"] = safe_float(matching_ratio.get("revenue"))
                earning_data["net_income"] = safe_float(matching_ratio.get("net_income"))
                earning_data["operating_margin"] = safe_float(matching_ratio.get("operating_margin"))
                results["ratios_matched"] += 1

            prepared_earnings.append(earning_data)

        # Empty fetch → no deletes (keeps older quarters outside the window).
        # Non-empty → drop same-announcement-date rows keyed under a different
        # quarter, then upsert on (company_id, quarter).
        results["earnings_saved"] = apply_incoming_earnings(
            db, company.id, prepared_earnings
        )

        print(f"Saved {results['earnings_saved']} earnings records ({results['ratios_matched']} enriched with ratios)\n")

        # ── STEP 3: Fetch and save SEC filings ──────────────
        print("Step 3: Fetching SEC filings...")

        if cik:
            for form_type in ["10-K", "10-Q"]:
                filings = get_recent_filings(cik, form_type=form_type, limit=3)

                for filing in filings:
                    filing_data = {
                        "form": filing.get("form"),
                        "date": filing.get("date"),
                        "accession": filing.get("accession"),
                        "raw_text": ""
                    }
                    row = save_filing(db, company.id, filing_data)
                    results["filings_saved"] += 1

                    # Fetch the primary-document HTML so the embedder can
                    # chunk it — without raw_text the filing can never enter
                    # the RAG index. Skipped when already fetched (dedupe on
                    # accession returns the existing row).
                    if row is not None and not row.raw_text:
                        html = fetch_filing_html(filing.get("accession"), cik)
                        if html:
                            row.raw_text = html
                            db.commit()
                            results["filings_fetched"] += 1
                        else:
                            logger.warning(
                                "filing_html_fetch_failed",
                                ticker=ticker,
                                accession=filing.get("accession"),
                            )

        print(
            f"Saved {results['filings_saved']} filing records "
            f"({results['filings_fetched']} with document HTML fetched)\n"
        )

        # ── STEP 4: Fetch and save news articles ────────────
        print("Step 4: Fetching news articles...")

        # Respect the NewsAPI daily quota (cross-process, Redis-backed).
        limiter = get_rate_limiter()
        limiter.acquire("newsapi")
        articles = get_company_news(
            company_data.get("name", ticker),
            ticker,
            days_back=30
        )
        logger.info(
            "newsapi_quota_remaining",
            ticker=ticker, remaining=limiter.get_remaining("newsapi"),
        )

        for article in articles:
            if not article.get("url"):
                continue

            save_news_article(db, company.id, article)
            results["articles_saved"] += 1

        print(f"Saved {results['articles_saved']} news articles\n")

    except Exception as e:
        results["errors"].append(str(e))
        print(f"Pipeline error: {e}")
        db.rollback()

    finally:
        db.close()

    print(f"{'='*50}")
    print(f"Pipeline complete for {ticker}")
    print(f"  Company ID:      {results['company_id']}")
    print(f"  Earnings saved:  {results['earnings_saved']}")
    print(f"  Ratios matched:  {results['ratios_matched']}")
    print(f"  Filings saved:   {results['filings_saved']} ({results['filings_fetched']} HTML fetched)")
    print(f"  Articles saved:  {results['articles_saved']}")
    if results["errors"]:
        print(f"  Errors:          {results['errors']}")
    print(f"{'='*50}\n")

    return results


def run_batch_ingestion(tickers: list) -> dict:
    """
    Run the ingestion pipeline for multiple tickers.
    A failure on one ticker does not stop the rest.
    """
    succeeded = []
    failed = []

    for ticker in tickers:
        try:
            result = run_ingestion_pipeline(ticker)
            if result.get("errors"):
                failed.append((ticker, "; ".join(result["errors"])))
            else:
                succeeded.append(ticker)
        except Exception as e:
            failed.append((ticker, str(e)))
            print(f"Pipeline failed for {ticker}: {e}")

    print(f"\n{'='*50}")
    print(f"Batch ingestion summary")
    print(f"{'='*50}")
    print(f"Total:     {len(tickers)}")
    print(f"Succeeded: {len(succeeded)} -> {succeeded}")
    print(f"Failed:    {len(failed)}")
    for ticker, err in failed:
        print(f"  {ticker}: {err}")
    print(f"{'='*50}\n")

    return {"succeeded": succeeded, "failed": failed}


if __name__ == "__main__":
    run_batch_ingestion([
        "NVDA", "META", "BRK-B", "JPM", "V",
        "JNJ", "WMT", "PG", "MA", "HD",
        "BAC", "XOM", "CVX", "ABBV", "MRK",
        "LLY", "PEP", "KO", "AVGO", "COST",
        "TMO", "MCD", "ACN", "DHR", "NEE",
        "TXN", "PM", "UNH", "RTX", "QCOM",
        "IBM", "GE", "CAT", "SPGI", "BLK",
        "INTU", "ISRG", "AMAT", "ADP", "MDLZ"
    ])