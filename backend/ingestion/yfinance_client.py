import yfinance as yf
import os
from dotenv import load_dotenv

load_dotenv()


def get_company_overview(ticker: str) -> dict:
    """
    Fetch basic company information and key metrics.
    """
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        return {
            "ticker": ticker,
            "name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "analyst_target": info.get("targetMeanPrice"),
            "recommendation": info.get("recommendationKey"),
        }
    except Exception as e:
        print(f"Error fetching overview for {ticker}: {e}")
        return {}


def get_quarterly_financials(ticker: str) -> dict:
    """
    Fetch last 4 quarters of key financial metrics.
    """
    try:
        stock = yf.Ticker(ticker)

        income = stock.quarterly_income_stmt
        balance = stock.quarterly_balance_sheet
        cashflow = stock.quarterly_cashflow

        return {
            "income_statement": income,
            "balance_sheet": balance,
            "cashflow": cashflow,
        }
    except Exception as e:
        print(f"Error fetching financials for {ticker}: {e}")
        return {}


def get_earnings_history(ticker: str) -> list:
    """
    Fetch earnings history — actual vs estimated EPS.
    """
    try:
        stock = yf.Ticker(ticker)
        earnings = stock.earnings_dates

        if earnings is None or earnings.empty:
            print(f"No earnings data found for {ticker}")
            return []

        results = []
        for date, row in earnings.iterrows():
            results.append({
                "date": str(date.date()),
                "eps_estimate": row.get("EPS Estimate"),
                "eps_actual": row.get("Reported EPS"),
                "surprise_pct": row.get("Surprise(%)"),
            })

        return results[:8]  # last 8 quarters

    except Exception as e:
        print(f"Error fetching earnings for {ticker}: {e}")
        return []


def get_price_history(ticker: str, period: str = "1y") -> dict:
    """
    Fetch historical price data.
    period options: 1mo, 3mo, 6mo, 1y, 2y
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)

        return {
            "ticker": ticker,
            "period": period,
            "start": str(hist.index[0].date()),
            "end": str(hist.index[-1].date()),
            "data_points": len(hist),
            "latest_close": round(hist["Close"].iloc[-1], 2),
            "highest": round(hist["High"].max(), 2),
            "lowest": round(hist["Low"].min(), 2),
        }
    except Exception as e:
        print(f"Error fetching price history for {ticker}: {e}")
        return {}


# Quick test when running this file directly
if __name__ == "__main__":
    ticker = "AAPL"
    print(f"Testing yfinance client for {ticker}...\n")

    print("--- Company Overview ---")
    overview = get_company_overview(ticker)
    for key, value in overview.items():
        print(f"  {key}: {value}")

    print("\n--- Price History (1 year) ---")
    price = get_price_history(ticker, period="1y")
    for key, value in price.items():
        print(f"  {key}: {value}")

    print("\n--- Earnings History ---")
    earnings = get_earnings_history(ticker)
    for e in earnings[:4]:
        print(f"  {e['date']} | estimate: {e['eps_estimate']} | actual: {e['eps_actual']} | surprise: {e['surprise_pct']}%")