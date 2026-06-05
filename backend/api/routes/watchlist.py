"""
Watchlist routes: track tickers and surface their latest-report summary.

  GET    /watchlist          -> list tracked tickers
  POST   /watchlist          -> add a ticker (must exist in companies)
  DELETE /watchlist/{ticker}  -> remove a ticker
  GET    /watchlist/summary   -> per-ticker latest risk/confidence/timestamp
"""
import structlog
from fastapi import APIRouter, HTTPException

from backend.api.schemas.requests import WatchlistAddRequest
from backend.api.schemas.responses import WatchlistItem, WatchlistSummaryItem
from backend.db.models import Company, Report, Watchlist
from backend.db.session import SessionLocal

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/watchlist", response_model=list[WatchlistItem])
def list_watchlist() -> list[WatchlistItem]:
    db = SessionLocal()
    try:
        rows = db.query(Watchlist).order_by(Watchlist.created_at.desc()).all()
        return [
            WatchlistItem(ticker=w.ticker, notes=w.notes, created_at=w.created_at)
            for w in rows
        ]
    finally:
        db.close()


@router.post("/watchlist", response_model=WatchlistItem)
def add_to_watchlist(request: WatchlistAddRequest) -> WatchlistItem:
    ticker = request.ticker.upper()
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.ticker == ticker).first()
        if not company:
            raise HTTPException(
                status_code=400,
                detail=f"{ticker} not in database -- run ingestion first",
            )
        existing = db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
        if existing:
            existing.notes = request.notes if request.notes is not None else existing.notes
            db.commit()
            db.refresh(existing)
            return WatchlistItem(
                ticker=existing.ticker, notes=existing.notes,
                created_at=existing.created_at,
            )
        item = Watchlist(ticker=ticker, notes=request.notes)
        db.add(item)
        db.commit()
        db.refresh(item)
        logger.info("watchlist_add", ticker=ticker)
        return WatchlistItem(ticker=item.ticker, notes=item.notes, created_at=item.created_at)
    finally:
        db.close()


@router.delete("/watchlist/{ticker}")
def remove_from_watchlist(ticker: str) -> dict:
    ticker = ticker.upper()
    db = SessionLocal()
    try:
        item = db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"{ticker} not on watchlist")
        db.delete(item)
        db.commit()
        logger.info("watchlist_remove", ticker=ticker)
        return {"removed": ticker}
    finally:
        db.close()


@router.get("/watchlist/summary", response_model=list[WatchlistSummaryItem])
def watchlist_summary() -> list[WatchlistSummaryItem]:
    """Most-recent report's risk/confidence/timestamp per watchlist ticker."""
    db = SessionLocal()
    try:
        out: list[WatchlistSummaryItem] = []
        rows = db.query(Watchlist).order_by(Watchlist.created_at.desc()).all()
        for w in rows:
            company = db.query(Company).filter(Company.ticker == w.ticker).first()
            latest = None
            if company:
                latest = (
                    db.query(Report)
                    .filter(Report.company_id == company.id)
                    .order_by(Report.generated_at.desc())
                    .first()
                )
            out.append(WatchlistSummaryItem(
                ticker=w.ticker,
                notes=w.notes,
                risk_level=latest.risk_level if latest else None,
                confidence_score=latest.confidence_score if latest else None,
                last_analyzed=latest.generated_at if latest else None,
            ))
        return out
    finally:
        db.close()
