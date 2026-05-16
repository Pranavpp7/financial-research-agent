import requests
import os
from dotenv import load_dotenv

load_dotenv()

# SEC requires a User-Agent header identifying who you are
HEADERS = {
    "User-Agent": f"financial-research-agent {os.getenv('USER_EMAIL', 'test@email.com')}"
}

BASE_URL = "https://data.sec.gov"


def get_company_info(cik: str) -> dict:
    """
    Fetch basic company information from SEC EDGAR.
    CIK is the unique company identifier on SEC (e.g. '0000320193' for Apple)
    """
    url = f"{BASE_URL}/submissions/CIK{cik}.json"
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()  # raises error if status != 200
        data = response.json()
        
        return {
            "name": data.get("name"),
            "cik": data.get("cik"),
            "sic_description": data.get("sicDescription"),
            "ticker": data.get("tickers", [None])[0],
            "exchange": data.get("exchanges", [None])[0],
        }
    except requests.RequestException as e:
        print(f"Error fetching company info for CIK {cik}: {e}")
        return {}


def get_recent_filings(cik: str, form_type: str = "10-K", limit: int = 5) -> list:
    """
    Fetch recent filings for a company.
    form_type: '10-K' for annual, '10-Q' for quarterly
    """
    url = f"{BASE_URL}/submissions/CIK{cik}.json"
    
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        data = response.json()
        
        filings = data["filings"]["recent"]
        results = []
        
        for i in range(len(filings["form"])):
            if filings["form"][i] == form_type:
                results.append({
                    "form": filings["form"][i],
                    "date": filings["filingDate"][i],
                    "document": filings["primaryDocument"][i],
                    "accession": filings["accessionNumber"][i],
                })
            if len(results) >= limit:
                break
                
        return results
    
    except requests.RequestException as e:
        print(f"Error fetching filings for CIK {cik}: {e}")
        return []


def fetch_filing_html(accession_number: str, cik: str) -> str:
    """
    Fetch the raw HTML of a filing's primary document from EDGAR.
    Returns "" on error.

    Heuristic: the primary document is the LARGEST .htm/.html in the
    filing directory that isn't an index, an exhibit, or an R-prefixed
    XBRL rendering file. (SEC filings include many small exhibits and
    XBRL fragments alongside the actual 10-K/10-Q narrative.)
    """
    cik_int = str(int(cik))
    accession_no_dashes = accession_number.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}"

    try:
        index_resp = requests.get(f"{base}/index.json", headers=HEADERS, timeout=30)
        index_resp.raise_for_status()
        items = index_resp.json().get("directory", {}).get("item", [])

        candidates = []
        for item in items:
            name = item.get("name", "")
            lower = name.lower()
            if not lower.endswith((".htm", ".html")):
                continue
            if "index" in lower or "exhibit" in lower:
                continue
            # R1.htm, R2.htm ... are XBRL rendering fragments, not narrative
            if lower.startswith("r") and lower.split(".")[0][1:].isdigit():
                continue
            try:
                size = int(item.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            candidates.append((size, name))

        if not candidates:
            return ""
        candidates.sort(reverse=True)
        primary = candidates[0][1]

        doc_resp = requests.get(f"{base}/{primary}", headers=HEADERS, timeout=60)
        doc_resp.raise_for_status()
        return doc_resp.text

    except Exception as e:
        print(f"Error fetching filing HTML {accession_number}: {e}")
        return ""


def fetch_filing_text(accession_number: str, cik: str) -> str:
    """
    Fetch the primary document of a filing from EDGAR and return it as
    plain text (HTML stripped). Returns "" on error.

    accession_number: SEC accession (e.g. '0000320193-25-000123')
    cik: company CIK -- leading zeros are stripped for the URL path.
    """
    # bs4 ships transitively via yfinance; imported here so the rest of
    # this module still loads if bs4 ever disappears.
    from bs4 import BeautifulSoup

    cik_int = str(int(cik))
    accession_no_dashes = accession_number.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}"

    try:
        index_resp = requests.get(f"{base}/index.json", headers=HEADERS, timeout=30)
        index_resp.raise_for_status()
        items = index_resp.json().get("directory", {}).get("item", [])

        primary = None
        for item in items:
            name = item.get("name", "")
            if name.lower().endswith((".htm", ".html")) and "index" not in name.lower():
                primary = name
                break
        if not primary:
            return ""

        doc_resp = requests.get(f"{base}/{primary}", headers=HEADERS, timeout=60)
        doc_resp.raise_for_status()

        soup = BeautifulSoup(doc_resp.text, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        lines = [line.strip() for line in text.splitlines()]
        return " ".join(line for line in lines if line)

    except Exception as e:
        print(f"Error fetching filing text {accession_number}: {e}")
        return ""


# Quick test when running this file directly
if __name__ == "__main__":
    print("Testing EDGAR client...\n")
    
    # Apple's CIK
    cik = "0000320193"
    
    info = get_company_info(cik)
    print("Company Info:")
    for key, value in info.items():
        print(f"  {key}: {value}")
    
    print("\nRecent 10-K Filings:")
    filings = get_recent_filings(cik, form_type="10-K")
    for f in filings:
        print(f"  {f['date']} | {f['form']} | {f['document']}")
    
    print("\nRecent 10-Q Filings:")
    filings = get_recent_filings(cik, form_type="10-Q")
    for f in filings:
        print(f"  {f['date']} | {f['form']} | {f['document']}")