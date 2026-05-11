from newsapi import NewsApiClient
from dotenv import load_dotenv
import os

load_dotenv()
API_KEY = os.getenv("NEWSAPI_KEY")

newsapi = NewsApiClient(api_key=API_KEY)

# Get news about Apple from last 30 days
articles = newsapi.get_everything(
    q="Apple Inc stock",
    language="en",
    sort_by="publishedAt",
    page_size=5
)

print(f"Total articles found: {articles['totalResults']}")
print("\n--- Latest Articles ---")
for article in articles['articles']:
    print(f"Title: {article['title']}")
    print(f"Source: {article['source']['name']}")
    print(f"Published: {article['publishedAt']}")
    print("---")