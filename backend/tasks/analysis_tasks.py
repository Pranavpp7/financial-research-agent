"""Celery tasks that wrap the agent pipeline."""
from backend.agents.run_agent import analyze
from backend.tasks.celery_app import celery_app


@celery_app.task(name="run_analysis", bind=True)
def run_analysis_task(self, ticker: str, question: str) -> dict:
    """
    Run the full supervisor -> analyzer -> synthesizer pipeline.
    Returns the report dict (already JSON-serializable -- contains
    bull_case, bear_case, risk_level, confidence_score, key_findings,
    sources, report_id). On exception, returns {"error": ...}.
    """
    try:
        return analyze(ticker, question)
    except Exception as e:
        return {
            "error": str(e),
            "ticker": ticker,
            "question": question,
        }
