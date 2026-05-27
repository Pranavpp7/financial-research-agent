"""
Entry point for the financial-research agent.

Pipeline: Supervisor decides analyses -> Analyzer runs each ->
Synthesizer combines into final structured report (saved to DB).

`analyze()` accepts an optional `progress_cb(meta: dict)` that is invoked
at each stage (supervisor / analyzing / per-analysis / synthesizing) so a
Celery task can stream progress to the frontend. It defaults to a no-op,
so direct/CLI callers are unaffected.
"""
import time
from typing import Callable, Optional

import structlog

from backend.agents.analyzer import Analyzer
from backend.agents.supervisor import Supervisor
from backend.agents.synthesizer import Synthesizer
from backend.db.models import Company
from backend.db.session import SessionLocal

logger = structlog.get_logger(__name__)

ProgressCb = Callable[[dict], None]


def _noop(_meta: dict) -> None:
    return None


def analyze(
    ticker: str,
    question: str,
    progress_cb: Optional[ProgressCb] = None,
) -> dict:
    emit = progress_cb or _noop
    ticker = ticker.upper()

    # Look up company
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.ticker == ticker).first()
        if not company:
            logger.warning("unknown_ticker", ticker=ticker)
            return {"error": f"unknown ticker {ticker}"}
        company_id = company.id
        company_name = company.name
    finally:
        db.close()

    run_start = time.perf_counter()
    logger.info("agent_run_start", ticker=ticker, company=company_name, question=question)

    # 1. Supervisor decides which analyses to run
    emit({"stage": "supervisor", "message": "Routing question to analyses...", "pct": 10})
    t0 = time.perf_counter()
    supervisor = Supervisor()
    chosen = supervisor.decide(ticker, question)
    logger.info(
        "supervisor_done", ticker=ticker, chosen=chosen,
        elapsed_s=round(time.perf_counter() - t0, 3),
    )

    # 2. Analyzer runs each type in sequence
    emit({"stage": "analyzing", "message": f"Running {', '.join(chosen)} analyses...", "pct": 30})
    analyzer = Analyzer()
    analyses = []
    step = 40 // len(chosen) if chosen else 40
    for idx, analysis_type in enumerate(chosen):
        t1 = time.perf_counter()
        result = analyzer.analyze(analysis_type, ticker, company_id, question)
        analyses.append(result)
        if result.get("error"):
            logger.error("analysis_failed", ticker=ticker, analysis=analysis_type, error=result["error"])
        else:
            logger.info(
                "analysis_done", ticker=ticker, analysis=analysis_type,
                elapsed_s=round(time.perf_counter() - t1, 3),
            )
        emit({
            "stage": f"analysis:{analysis_type}",
            "message": f"Completed {analysis_type} analysis",
            "pct": 30 + (idx + 1) * step,
        })

    # 3. Synthesizer combines into final report
    emit({"stage": "synthesizing", "message": "Synthesizing final report...", "pct": 80})
    t2 = time.perf_counter()
    synthesizer = Synthesizer()
    report = synthesizer.synthesize(ticker, company_id, analyses)
    logger.info(
        "synthesis_done", ticker=ticker, report_id=report.get("report_id"),
        elapsed_s=round(time.perf_counter() - t2, 3),
    )
    logger.info(
        "agent_run_complete", ticker=ticker,
        total_elapsed_s=round(time.perf_counter() - run_start, 3),
        risk_level=report.get("risk_level"),
    )

    # 4. Print
    print(f"\n{'='*88}")
    print(f"FINAL REPORT  (report_id={report.get('report_id', 'unsaved')})")
    print(f"{'='*88}")
    if "error" in report:
        print(f"ERROR: {report['error']}")
        if "raw" in report:
            print(f"\nRaw response:\n{report['raw']}")
        return report

    print(f"\nRISK LEVEL: {str(report.get('risk_level', 'unknown')).upper()}")
    print(f"CONFIDENCE: {report.get('confidence_score', 0.0):.2f}")
    print(f"\nBULL CASE:\n  {report.get('bull_case', '')}")
    print(f"\nBEAR CASE:\n  {report.get('bear_case', '')}")

    findings = report.get("key_findings", [])
    if findings:
        print(f"\nKEY FINDINGS:")
        for f in findings:
            print(f"  - {f}")

    sources = report.get("sources", [])
    if sources:
        print(f"\nSOURCES:")
        for s in sources:
            print(f"  - {s}")
    print(f"{'='*88}\n")

    return report


if __name__ == "__main__":
    analyze("AAPL", "Give me a comprehensive analysis of Apple stock")
