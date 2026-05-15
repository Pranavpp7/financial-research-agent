import os
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from backend.db.models import (
    Company, Filing, Earning,
    NewsArticle, MLPrediction, Report,
    ReportCitation, AgentRun, EvalScore
)


# ─── COMPANY ────────────────────────────────────────────────

def get_or_create_company(db: Session, ticker: str, data: dict) -> Company:
    """
    Get existing company or create new one.
    Updates info if company already exists.
    Strategy: update in place (company info rarely changes)
    """
    company = db.query(Company).filter(Company.ticker == ticker).first()

    if company:
        # Update existing record with fresh data
        company.name = data.get("name", company.name)
        company.sector = data.get("sector", company.sector)
        company.industry = data.get("industry", company.industry)
        company.exchange = data.get("exchange", company.exchange)
        company.cik = data.get("cik", company.cik)
        company.last_analyzed = datetime.utcnow()
        db.commit()
        db.refresh(company)
        print(f"Updated company: {ticker}")
    else:
        # Create new record
        company = Company(
            ticker=ticker,
            name=data.get("name"),
            sector=data.get("sector"),
            industry=data.get("industry"),
            exchange=data.get("exchange"),
            cik=data.get("cik"),
            last_analyzed=datetime.utcnow()
        )
        db.add(company)
        db.commit()
        db.refresh(company)
        print(f"Created company: {ticker}")

    return company


def get_company(db: Session, ticker: str) -> Company:
    """Get company by ticker."""
    return db.query(Company).filter(Company.ticker == ticker).first()


# ─── FILINGS ────────────────────────────────────────────────

def save_filing(db: Session, company_id: int, data: dict) -> Filing:
    """
    Save SEC filing.
    Strategy: append only, skip if accession number already exists.
    Accession number is SEC's unique ID for each filing.
    """
    existing = db.query(Filing).filter(
        Filing.accession_number == data.get("accession")
    ).first()

    if existing:
        print(f"Filing already exists: {data.get('accession')}")
        return existing

    filing = Filing(
        company_id=company_id,
        form_type=data.get("form"),
        filed_date=datetime.strptime(data.get("date"), "%Y-%m-%d") if data.get("date") else None,
        accession_number=data.get("accession"),
        raw_text=data.get("raw_text", ""),
        is_embedded=0
    )
    db.add(filing)
    db.commit()
    db.refresh(filing)
    print(f"Saved filing: {data.get('form')} - {data.get('date')}")
    return filing


def get_filings(db: Session, company_id: int, form_type: str = None):
    """Get all filings for a company, optionally filtered by type."""
    query = db.query(Filing).filter(Filing.company_id == company_id)
    if form_type:
        query = query.filter(Filing.form_type == form_type)
    return query.order_by(Filing.filed_date.desc()).all()


# ─── EARNINGS ───────────────────────────────────────────────

def save_earning(db: Session, company_id: int, data: dict) -> Earning:
    """
    Save quarterly earnings data.
    Strategy: upsert on (company_id, quarter)
    Same quarter updated if already exists.
    """
    existing = db.query(Earning).filter(
        Earning.company_id == company_id,
        Earning.quarter == data.get("quarter")
    ).first()

    if existing:
        # Update with latest data
        existing.eps_estimate = data.get("eps_estimate", existing.eps_estimate)
        existing.eps_actual = data.get("eps_actual", existing.eps_actual)
        existing.surprise_pct = data.get("surprise_pct", existing.surprise_pct)
        existing.revenue = data.get("revenue", existing.revenue)
        existing.net_income = data.get("net_income", existing.net_income)
        existing.operating_margin = data.get("operating_margin", existing.operating_margin)
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        print(f"Updated earnings: {data.get('quarter')}")
        return existing

    earning = Earning(
        company_id=company_id,
        quarter=data.get("quarter"),
        report_date=datetime.strptime(data.get("date"), "%Y-%m-%d") if data.get("date") else None,
        eps_estimate=data.get("eps_estimate"),
        eps_actual=data.get("eps_actual"),
        surprise_pct=data.get("surprise_pct"),
        revenue=data.get("revenue"),
        net_income=data.get("net_income"),
        operating_margin=data.get("operating_margin"),
    )
    db.add(earning)
    db.commit()
    db.refresh(earning)
    print(f"Saved earnings: {data.get('quarter')}")
    return earning


def get_earnings(db: Session, company_id: int, limit: int = 8):
    """Get earnings history for a company."""
    return db.query(Earning).filter(
        Earning.company_id == company_id
    ).order_by(Earning.report_date.desc()).limit(limit).all()


# ─── NEWS ARTICLES ──────────────────────────────────────────

def save_news_article(db: Session, company_id: int, data: dict) -> NewsArticle:
    """
    Save news article.
    Strategy: INSERT ... DO NOTHING if URL already exists.
    URL is the unique identifier for each article.
    """
    existing = db.query(NewsArticle).filter(
        NewsArticle.url == data.get("url")
    ).first()

    if existing:
        return existing

    published_at = None
    if data.get("published_at"):
        try:
            published_at = datetime.fromisoformat(
                data["published_at"].replace("Z", "+00:00")
            )
        except:
            pass

    article = NewsArticle(
        company_id=company_id,
        title=data.get("title"),
        description=data.get("description"),
        url=data.get("url"),
        source=data.get("source"),
        published_at=published_at,
        sentiment_score=None,
        sentiment_label=None
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    print(f"Saved article: {data.get('title', '')[:50]}")
    return article


def get_news_articles(db: Session, company_id: int, limit: int = 20):
    """Get recent news articles for a company."""
    return db.query(NewsArticle).filter(
        NewsArticle.company_id == company_id
    ).order_by(NewsArticle.published_at.desc()).limit(limit).all()


# ─── ML PREDICTIONS ─────────────────────────────────────────

def save_ml_prediction(db: Session, company_id: int, data: dict) -> MLPrediction:
    """Save ML model prediction with SHAP values."""
    prediction = MLPrediction(
        company_id=company_id,
        model_name=data.get("model_name"),
        prediction=data.get("prediction"),
        confidence=data.get("confidence"),
        shap_values=data.get("shap_values"),
        features_used=data.get("features_used"),
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    print(f"Saved ML prediction: {data.get('model_name')}")
    return prediction


def get_latest_prediction(db: Session, company_id: int, model_name: str):
    """Get the most recent prediction from a specific model."""
    return db.query(MLPrediction).filter(
        MLPrediction.company_id == company_id,
        MLPrediction.model_name == model_name
    ).order_by(MLPrediction.run_date.desc()).first()


# ─── REPORTS ────────────────────────────────────────────────

def save_report(db: Session, company_id: int, data: dict) -> Report:
    """Save generated research report."""
    report = Report(
        company_id=company_id,
        bull_case=data.get("bull_case"),
        bear_case=data.get("bear_case"),
        risk_level=data.get("risk_level"),
        overall_sentiment=data.get("overall_sentiment"),
        confidence_score=data.get("confidence_score"),
        sources=data.get("sources", [])
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    print(f"Saved report for company_id: {company_id}")
    return report


def get_latest_report(db: Session, company_id: int) -> Report:
    """Get the most recent report for a company."""
    return db.query(Report).filter(
        Report.company_id == company_id
    ).order_by(Report.generated_at.desc()).first()


# ─── TEST ───────────────────────────────────────────────────

if __name__ == "__main__":
    from backend.db.session import SessionLocal

    db = SessionLocal()

    print("Testing CRUD operations...\n")

    # Test create company
    company = get_or_create_company(db, "AAPL", {
        "name": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "exchange": "Nasdaq",
        "cik": "0000320193"
    })
    print(f"Company ID: {company.id}")

    # Test save earnings
    earning = save_earning(db, company.id, {
        "quarter": "2026-Q1",
        "date": "2026-04-30",
        "eps_estimate": 1.94,
        "eps_actual": 2.01,
        "surprise_pct": 3.49
    })
    print(f"Earning ID: {earning.id}")

    # Test save news
    article = save_news_article(db, company.id, {
        "title": "Apple beats Q1 earnings estimates",
        "description": "Apple reported strong Q1 results",
        "url": "https://example.com/apple-q1-2026",
        "source": "Reuters",
        "published_at": "2026-04-30T12:00:00Z"
    })
    print(f"Article ID: {article.id}")

    # Read back
    print(f"\nVerification:")
    print(f"Company: {company.name} ({company.ticker})")
    print(f"Earnings quarter: {earning.quarter}, surprise: {earning.surprise_pct}%")
    print(f"Article: {article.title}")

    db.close()
    print("\nAll CRUD operations successful!")