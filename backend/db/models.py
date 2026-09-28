from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Text,
    DateTime, ForeignKey, UniqueConstraint, JSON
)
from sqlalchemy.orm import declarative_base, relationship
from pgvector.sqlalchemy import Vector

Base = declarative_base()


def utcnow() -> datetime:
    """
    Naive UTC timestamp for column defaults.

    Replaces the deprecated `datetime.utcnow`. We strip tzinfo so the value
    matches the naive `TIMESTAMP WITHOUT TIME ZONE` columns exactly as before
    (read-side code re-attaches UTC), keeping behavior identical with no
    migration required.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Company(Base):
    """
    Core table — every other table links back to this.
    One row per company we track.
    """
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(10), unique=True, nullable=False)
    name = Column(String(255))
    sector = Column(String(100))
    industry = Column(String(100))
    exchange = Column(String(50))
    cik = Column(String(20))          # SEC identifier
    last_analyzed = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)

    # Relationships — lets us do company.filings, company.earnings etc
    filings = relationship("Filing", back_populates="company")
    earnings = relationship("Earning", back_populates="company")
    news_articles = relationship("NewsArticle", back_populates="company")
    ml_predictions = relationship("MLPrediction", back_populates="company")
    reports = relationship("Report", back_populates="company")


class Filing(Base):
    """
    SEC filings — 10-K (annual) and 10-Q (quarterly).
    Raw text stored here, chunks stored in FilingChunk.
    """
    __tablename__ = "filings"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    form_type = Column(String(20))        # '10-K' or '10-Q'
    filed_date = Column(DateTime)
    accession_number = Column(String(50), unique=True)  # SEC unique ID
    raw_text = Column(Text)
    is_embedded = Column(Integer, default=0)  # 0=no, 1=yes
    created_at = Column(DateTime, default=utcnow)

    company = relationship("Company", back_populates="filings")
    chunks = relationship("FilingChunk", back_populates="filing")

    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_filing_accession"),
    )


class FilingChunk(Base):
    """
    SEC filings broken into 500-token chunks for RAG.
    Each chunk gets embedded by Voyage AI and stored as a vector.
    Vector search happens over this table via pgvector.
    """
    __tablename__ = "filing_chunks"

    id = Column(Integer, primary_key=True)
    filing_id = Column(Integer, ForeignKey("filings.id"), nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer)         # position in the filing
    embedding = Column(Vector(1024))      # BAAI/bge-large-en-v1.5 dim, pgvector
    created_at = Column(DateTime, default=utcnow)

    filing = relationship("Filing", back_populates="chunks")


class Earning(Base):
    """
    Quarterly earnings data — actual vs estimated EPS.
    This is what the Earnings Surprise Predictor trains on.
    Strategy: upsert on (company_id, quarter)
    """
    __tablename__ = "earnings"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    quarter = Column(String(20))          # e.g. '2026-Q1'
    report_date = Column(DateTime)
    eps_estimate = Column(Float)
    eps_actual = Column(Float)
    surprise_pct = Column(Float)
    revenue = Column(Float)
    net_income = Column(Float)
    operating_margin = Column(Float)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    company = relationship("Company", back_populates="earnings")

    __table_args__ = (
        UniqueConstraint("company_id", "quarter", name="uq_earning_company_quarter"),
    )


class NewsArticle(Base):
    """
    News articles fetched from NewsAPI.
    Deduplicated by URL — same article never stored twice.
    Sentiment score added by FinBERT after ingestion.
    Strategy: INSERT ... ON CONFLICT (url) DO NOTHING
    """
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    title = Column(String(500))
    description = Column(Text)
    url = Column(String(1000), unique=True)
    source = Column(String(100))
    published_at = Column(DateTime)
    sentiment_score = Column(Float)       # set by FinBERT later
    sentiment_label = Column(String(20))  # 'positive', 'negative', 'neutral'
    created_at = Column(DateTime, default=utcnow)

    company = relationship("Company", back_populates="news_articles")

    __table_args__ = (
        UniqueConstraint("url", name="uq_news_url"),
    )


class MLPrediction(Base):
    """
    Outputs from all ML models.
    One row per model per company per run.
    Includes SHAP values for explainability.
    """
    __tablename__ = "ml_predictions"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    model_name = Column(String(100))      # 'earnings_surprise', 'anomaly', etc
    prediction = Column(Float)
    confidence = Column(Float)
    shap_values = Column(JSON)            # feature importance dict
    features_used = Column(JSON)          # input features dict
    run_date = Column(DateTime, default=utcnow)

    company = relationship("Company", back_populates="ml_predictions")


class Report(Base):
    """
    Final research reports generated by the Synthesis Agent.
    Bull case, bear case, risk level all stored here.
    Sources stored as JSON array of citation references.
    """
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    generated_at = Column(DateTime, default=utcnow)
    bull_case = Column(Text)
    bear_case = Column(Text)
    risk_level = Column(String(20))       # 'low', 'medium', 'high'
    overall_sentiment = Column(String(20))
    confidence_score = Column(Float)
    data_quality = Column(Float)          # 0.0-1.0, freshness/completeness of inputs
    analyst_notes = Column(Text)          # caveats: data gaps, approximations
    sources = Column(JSON)                # list of source references
    cache_key = Column(String(128))       # hash(ticker, normalized_question, agent_version)
    question = Column(Text)               # the question that produced this report

    company = relationship("Company", back_populates="reports")
    citations = relationship("ReportCitation", back_populates="report")

    @property
    def age_minutes(self) -> int:
        """Whole minutes since this report was generated (UTC-aware)."""
        if not self.generated_at:
            return 0
        ref = self.generated_at
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - ref).total_seconds() // 60)
    agent_runs = relationship("AgentRun", back_populates="report")
    eval_scores = relationship("EvalScore", back_populates="report")


class ReportCitation(Base):
    """
    Every claim in a report linked to its source.
    This is what makes reports trustworthy and auditable.
    """
    __tablename__ = "report_citations"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    claim_text = Column(Text)
    source_type = Column(String(50))      # 'filing', 'earnings', 'news', 'ml_model'
    source_id = Column(Integer)           # ID in the relevant table
    confidence = Column(Float)
    created_at = Column(DateTime, default=utcnow)

    report = relationship("Report", back_populates="citations")


class AgentRun(Base):
    """
    Logs every agent execution for observability.
    Feeds LangSmith and Prometheus dashboards.
    """
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    agent_name = Column(String(100))      # 'sec_agent', 'earnings_agent', etc
    input_data = Column(JSON)
    output_data = Column(JSON)
    latency_ms = Column(Integer)
    tokens_used = Column(Integer)
    status = Column(String(20))           # 'success', 'failed'
    created_at = Column(DateTime, default=utcnow)

    report = relationship("Report", back_populates="agent_runs")


class Watchlist(Base):
    """
    User watchlist of tickers. One row per tracked ticker (no auth/multi-user
    yet, so the table is effectively a single global list).
    """
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(10), unique=True, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    last_analyzed_at = Column(DateTime)   # stamped by the nightly scheduled task

    __table_args__ = (
        UniqueConstraint("ticker", name="uq_watchlist_ticker"),
    )


class ScheduledRun(Base):
    """One row per scheduled (Celery beat) task execution, for observability."""
    __tablename__ = "scheduled_runs"

    id = Column(Integer, primary_key=True)
    task_name = Column(String(100))
    ran_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime)
    status = Column(String(20))           # 'running' | 'completed' | 'failed'
    summary = Column(JSON)
    error = Column(Text)


class AlertSubscription(Base):
    """A subscription to alerts for a ticker via email or Slack."""
    __tablename__ = "alert_subscriptions"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(10), nullable=False)
    channel = Column(String(20))          # 'email' | 'slack'
    destination = Column(String(500))     # email address or Slack webhook URL
    triggers = Column(JSON)               # list[str] of trigger types
    active = Column(Integer, default=1)    # 1=active, 0=inactive
    created_at = Column(DateTime, default=utcnow)
    last_fired_at = Column(DateTime)


class AlertHistory(Base):
    """One row per alert delivery attempt."""
    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, ForeignKey("alert_subscriptions.id"), nullable=False)
    fired_at = Column(DateTime, default=utcnow)
    trigger_type = Column(String(50))
    report_id_before = Column(Integer, ForeignKey("reports.id"))
    report_id_after = Column(Integer, ForeignKey("reports.id"))
    payload = Column(JSON)
    delivery_status = Column(String(20))  # 'sent' | 'failed'
    delivery_error = Column(Text)


class BacktestRun(Base):
    """A single backtest execution over a set of historical reports."""
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True)
    name = Column(String(200))
    created_at = Column(DateTime, default=utcnow)
    parameters = Column(JSON)
    summary = Column(JSON)
    status = Column(String(20))           # 'running' | 'completed' | 'failed'
    error = Column(Text)


class BacktestResult(Base):
    """Per-report result within a backtest run."""
    __tablename__ = "backtest_results"

    id = Column(Integer, primary_key=True)
    backtest_run_id = Column(Integer, ForeignKey("backtest_runs.id"), nullable=False)
    report_id = Column(Integer, ForeignKey("reports.id"))
    ticker = Column(String(10))
    report_date = Column(DateTime)
    signal = Column(String(10))           # 'bullish' | 'bearish' | 'neutral'
    confidence_score = Column(Float)
    risk_level = Column(String(20))
    entry_price = Column(Float)
    exit_price_30d = Column(Float)
    exit_price_90d = Column(Float)
    return_30d = Column(Float)
    return_90d = Column(Float)
    hit = Column(Integer)                 # 1=hit, 0=miss, null=excluded/unknown


class EvalScore(Base):
    """
    Ragas evaluation scores per report.
    Tracks quality of RAG system over time.
    """
    __tablename__ = "eval_scores"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("reports.id"), nullable=False)
    faithfulness = Column(Float)          # did agent make things up?
    relevancy = Column(Float)             # legacy alias of answer_relevancy
    answer_relevancy = Column(Float)      # Ragas answer_relevancy metric
    context_precision = Column(Float)     # did it use the right sources?
    context_recall = Column(Float)        # needs ground_truth; null otherwise
    ragas_score = Column(Float)           # overall score
    evaluated_at = Column(DateTime, default=utcnow)

    report = relationship("Report", back_populates="eval_scores")