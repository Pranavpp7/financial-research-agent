import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from newsapi import NewsApiClient

load_dotenv()


def get_client():
    api_key = os.getenv("NEWSAPI_KEY")
    if not api_key:
        raise ValueError("NEWSAPI_KEY not found in .env file")
    return NewsApiClient(api_key=api_key)


def get_company_news(company_name: str, ticker: str, days_back: int = 30) -> list:
    """
    Fetch recent news articles for a company.
    Uses targeted query to ensure financial relevance.
    """
    try:
        client = get_client()

        from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        response = client.get_everything(
            q=f'"{company_name}" AND (earnings OR revenue OR stock OR financial OR quarterly)',
            language="en",
            sort_by="publishedAt",
            from_param=from_date,
            page_size=20
        )

        articles = []
        for a in response.get("articles", []):
            articles.append({
                "title": a.get("title"),
                "source": a.get("source", {}).get("name"),
                "published_at": a.get("publishedAt"),
                "description": a.get("description"),
                "url": a.get("url"),
            })

        return articles

    except Exception as e:
        print(f"Error fetching news for {company_name}: {e}")
        return []


def get_market_news(category: str = "business", page_size: int = 10) -> list:
    """
    Fetch general market/business news headlines.
    """
    try:
        client = get_client()

        response = client.get_top_headlines(
            category=category,
            language="en",
            page_size=page_size
        )

        articles = []
        for a in response.get("articles", []):
            articles.append({
                "title": a.get("title"),
                "source": a.get("source", {}).get("name"),
                "published_at": a.get("publishedAt"),
                "description": a.get("description"),
            })

        return articles

    except Exception as e:
        print(f"Error fetching market news: {e}")
        return []


# Quick test when running this file directly
if __name__ == "__main__":
    print("Testing news client...\n")

    print("--- Apple News (last 30 days) ---")
    articles = get_company_news("Apple", "AAPL", days_back=30)
    print(f"Total articles: {len(articles)}")
    for a in articles[:3]:
        print(f"\n  Title: {a['title']}")
        print(f"  Source: {a['source']}")
        print(f"  Published: {a['published_at']}")
        print(f"  Description: {a['description']}")

    print("\n--- Top Business Headlines ---")
    headlines = get_market_news(category="business", page_size=5)
    for h in headlines:
        print(f"\n  Title: {h['title']}")
        print(f"  Source: {h['source']}")
        print(f"  Description: {h['description']}")