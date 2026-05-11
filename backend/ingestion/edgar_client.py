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