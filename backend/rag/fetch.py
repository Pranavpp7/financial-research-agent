"""
Pull a single company's most recent SEC filing HTML from EDGAR and
store it in filings.raw_text. Smoke-test step for the RAG pipeline.
"""
from backend.db.session import SessionLocal
from backend.db.models import Company, Filing
from backend.ingestion.edgar_client import fetch_filing_html


def main(ticker: str = "AAPL"):
    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.ticker == ticker).first()
        if not company:
            print(f"No company {ticker} in DB. Run the ingestion pipeline first.")
            return
        if not company.cik:
            print(f"{ticker} has no CIK on file.")
            return

        filing = (
            db.query(Filing)
            .filter(Filing.company_id == company.id)
            .order_by(Filing.filed_date.desc())
            .first()
        )
        if not filing:
            print(f"No filings recorded for {ticker}.")
            return

        if filing.raw_text:
            print(
                f"Filing {filing.id} already has raw_text "
                f"({len(filing.raw_text):,} chars). Nothing to do."
            )
            return

        print(
            f"Fetching {filing.form_type} for {ticker} "
            f"(accession {filing.accession_number})..."
        )
        html = fetch_filing_html(filing.accession_number, company.cik)
        if not html:
            print("Got empty response from EDGAR.")
            return

        print(f"Got {len(html):,} chars of HTML. Saving to filings.raw_text...")
        filing.raw_text = html
        # filing stays is_embedded=0 -- the embedder picks it up next.
        db.commit()
        print(f"Saved. Filing ID: {filing.id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
