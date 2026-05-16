"""
Entry point for the financial-research agent.

Pipeline: Supervisor decides analyses -> Analyzer runs each ->
Synthesizer combines into final structured report (saved to DB).
"""
from backend.agents.analyzer import Analyzer
from backend.agents.supervisor import Supervisor
from backend.agents.synthesizer import Synthesizer
from backend.db.models import Company
from backend.db.session import SessionLocal


def analyze(ticker: str, question: str) -> dict:
    ticker = ticker.upper()

    # Look up company
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.ticker == ticker).first()
        if not company:
            print(f"No company {ticker} in DB. Run the ingestion pipeline first.")
            return {"error": f"unknown ticker {ticker}"}
        company_id = company.id
        company_name = company.name
    finally:
        db.close()

    print(f"\n{'='*88}")
    print(f"Agent run: {ticker} ({company_name})")
    print(f"Question:  {question}")
    print(f"{'='*88}\n")

    # 1. Supervisor decides which analyses to run
    print("Step 1: supervisor deciding analyses...")
    supervisor = Supervisor()
    chosen = supervisor.decide(ticker, question)
    print(f"  selected: {chosen}\n")

    # 2. Analyzer runs each type in sequence
    print("Step 2: running analyses...")
    analyzer = Analyzer()
    analyses = []
    for analysis_type in chosen:
        print(f"  -> {analysis_type}")
        result = analyzer.analyze(analysis_type, ticker, company_id, question)
        analyses.append(result)
        if result.get("error"):
            print(f"     ERROR: {result['error']}")

    # 3. Synthesizer combines into final report
    print("\nStep 3: synthesizing final report...")
    synthesizer = Synthesizer()
    report = synthesizer.synthesize(ticker, company_id, analyses)

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
