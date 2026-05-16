"""
Analyzer: runs one specialized analysis (earnings | sec | news | risk).

Each type has its own data-loading function; the Groq call shape is shared.
The user's question is passed through to all analyses (and used as the
retrieval query for "sec").
"""
import os

from dotenv import load_dotenv
from groq import Groq

from backend.db.session import SessionLocal
from backend.db.models import Earning, MLPrediction, NewsArticle
from backend.agents.prompts import (
    EARNINGS_PROMPT, NEWS_PROMPT, RISK_PROMPT, SEC_PROMPT,
)
from backend.rag.retriever import search as rag_search

load_dotenv()


ANALYZER_MODEL = "llama-3.3-70b-versatile"

PROMPTS = {
    "earnings": EARNINGS_PROMPT,
    "sec": SEC_PROMPT,
    "news": NEWS_PROMPT,
    "risk": RISK_PROMPT,
}


def _format_earnings_context(db, company_id: int) -> str:
    earnings = (
        db.query(Earning)
        .filter(Earning.company_id == company_id)
        .order_by(Earning.report_date.desc())
        .limit(8)
        .all()
    )
    pred = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.company_id == company_id,
            MLPrediction.model_name == "earnings_surprise_predictor",
        )
        .order_by(MLPrediction.run_date.desc())
        .first()
    )

    lines = ["EARNINGS HISTORY (most recent first):"]
    if not earnings:
        lines.append("  (no earnings rows for this company)")
    for e in earnings:
        lines.append(
            f"  {e.quarter}  est={e.eps_estimate}  actual={e.eps_actual}  "
            f"surprise={e.surprise_pct}%  rev={e.revenue}  "
            f"net_income={e.net_income}  op_margin={e.operating_margin}"
        )

    lines.append("")
    if pred:
        lines.append("ML PREDICTION (earnings_surprise_predictor):")
        lines.append(
            f"  prediction={pred.prediction}  confidence={pred.confidence}"
        )
        if pred.shap_values:
            lines.append(f"  shap_values={pred.shap_values}")
        if pred.features_used:
            lines.append(f"  features_used={pred.features_used}")
    else:
        lines.append("ML PREDICTION (earnings_surprise_predictor): not available")
    return "\n".join(lines)


def _format_sec_context(question: str, ticker: str, k: int = 6) -> str:
    chunks = rag_search(question, k=k, ticker=ticker)
    if not chunks:
        return f"No SEC filing chunks indexed for {ticker} yet."
    blocks = []
    for c in chunks:
        header = f"[{c['ticker']} {c['form_type']} chunk #{c['chunk_index']}]"
        blocks.append(f"{header}\n{c['chunk_text']}")
    return "\n\n".join(blocks)


def _format_news_context(db, company_id: int) -> str:
    articles = (
        db.query(NewsArticle)
        .filter(NewsArticle.company_id == company_id)
        .filter(NewsArticle.sentiment_score.isnot(None))
        .order_by(NewsArticle.published_at.desc())
        .limit(20)
        .all()
    )
    pred = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.company_id == company_id,
            MLPrediction.model_name == "finbert_sentiment",
        )
        .order_by(MLPrediction.run_date.desc())
        .first()
    )

    lines = []
    if pred and pred.shap_values:
        lines.append("AGGREGATE SENTIMENT (finbert_sentiment):")
        for k, v in pred.shap_values.items():
            lines.append(f"  {k}: {v}")
        lines.append("")

    if not articles:
        lines.append("RECENT ARTICLES: none with sentiment scores")
    else:
        lines.append(f"RECENT ARTICLES ({len(articles)}):")
        for a in articles:
            score_str = (
                f"{a.sentiment_score:+.2f}"
                if a.sentiment_score is not None
                else "n/a"
            )
            lines.append(
                f"  [{a.sentiment_label} {score_str}] {a.title} -- {a.source}"
            )
    return "\n".join(lines)


def _format_risk_context(db, company_id: int) -> str:
    beneish = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.company_id == company_id,
            MLPrediction.model_name == "beneish_m_score",
        )
        .order_by(MLPrediction.run_date.desc())
        .first()
    )
    anomaly = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.company_id == company_id,
            MLPrediction.model_name == "anomaly_detector",
        )
        .order_by(MLPrediction.run_date.desc())
        .first()
    )

    lines = []
    if beneish:
        lines.append("BENEISH M-SCORE:")
        lines.append(
            f"  M-Score: {beneish.prediction}  confidence: {beneish.confidence}"
        )
        if beneish.shap_values:
            lines.append(f"  ratios: {beneish.shap_values}")
        if beneish.features_used:
            lines.append(f"  context: {beneish.features_used}")
    else:
        lines.append("BENEISH M-SCORE: not available")

    lines.append("")
    if anomaly:
        flagged = bool(anomaly.confidence and float(anomaly.confidence) >= 1.0)
        lines.append("ANOMALY DETECTOR (IsolationForest):")
        lines.append(
            f"  anomaly_score: {anomaly.prediction}  flagged: {flagged}"
        )
        if anomaly.shap_values:
            lines.append(f"  feature z-scores: {anomaly.shap_values}")
    else:
        lines.append("ANOMALY DETECTOR: not available")
    return "\n".join(lines)


class Analyzer:
    def __init__(self, model: str = ANALYZER_MODEL):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set in .env")
        self.client = Groq(api_key=api_key)
        self.model = model

    def analyze(
        self,
        analysis_type: str,
        ticker: str,
        company_id: int,
        question: str,
    ) -> dict:
        if analysis_type not in PROMPTS:
            return {
                "type": analysis_type,
                "text": "",
                "error": f"unknown analysis type: {analysis_type}",
            }

        # Build context per type
        if analysis_type == "sec":
            context = _format_sec_context(question, ticker)
        else:
            db = SessionLocal()
            try:
                if analysis_type == "earnings":
                    context = _format_earnings_context(db, company_id)
                elif analysis_type == "news":
                    context = _format_news_context(db, company_id)
                else:  # risk
                    context = _format_risk_context(db, company_id)
            finally:
                db.close()

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": PROMPTS[analysis_type]},
                    {"role": "user", "content": (
                        f"Question: {question}\n"
                        f"Ticker: {ticker}\n\n"
                        f"Data:\n{context}"
                    )},
                ],
                temperature=0.2,
            )
            text = response.choices[0].message.content
            return {"type": analysis_type, "text": text, "context": context}
        except Exception as e:
            return {"type": analysis_type, "text": "", "error": str(e)}
