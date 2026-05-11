import requests

# SEC EDGAR full-text search API - no API key needed
headers = {
    "User-Agent": "financial-research-agent youremail@gmail.com"
}

# Search for Apple's 10-K filings
url = "https://data.sec.gov/submissions/CIK0000320193.json"

response = requests.get(url, headers=headers)
data = response.json()

print("Company:", data["name"])
print("CIK:", data["cik"])
print("SIC Description:", data["sicDescription"])

# Get recent filings
filings = data["filings"]["recent"]
print("\n--- Recent Filings ---")
for i in range(5):
    print(f"{filings['form'][i]} | {filings['filingDate'][i]} | {filings['primaryDocument'][i]}")