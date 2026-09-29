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
            "exchange": info.get("exchange"),
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


def safe_float(value):
    """Convert numpy floats or any numeric type to plain Python float."""
    try:
        if value is None or str(value) == "nan":
            return None
        return float(value)
    except Exception:
        return None


def _lookup(df, label: str, col):
    """Get df.loc[label, col] safely; return None if df, label, or col is missing."""
    if df is None or df.empty:
        return None
    if label not in df.index or col not in df.columns:
        return None
    return safe_float(df.loc[label, col])


def _ratio(numerator, denominator):
    """Safe division with None propagation."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def get_key_financial_ratios(ticker: str) -> list:
    """
    Extract key financial metrics + derived ratios for the last 4 quarters.
    Returns a list of dicts, most recent quarter first.
    """
    try:
        financials = get_quarterly_financials(ticker)
        income = financials.get("income_statement")
        balance = financials.get("balance_sheet")
        cashflow = financials.get("cashflow")

        if income is None or income.empty:
            return []

        results = []
        for col in list(income.columns)[:4]:
            quarter = f"{col.year}-Q{(col.month - 1) // 3 + 1}"

            revenue = _lookup(income, "Total Revenue", col)
            gross_profit = _lookup(income, "Gross Profit", col)
            operating_income = _lookup(income, "Operating Income", col)
            net_income = _lookup(income, "Net Income", col)

            total_assets = _lookup(balance, "Total Assets", col)
            total_debt = _lookup(balance, "Total Debt", col)
            if total_debt is None:
                total_debt = _lookup(balance, "Long Term Debt", col)
            cash = _lookup(balance, "Cash And Cash Equivalents", col)

            operating_cashflow = _lookup(cashflow, "Operating Cash Flow", col)
            capital_expenditure = _lookup(cashflow, "Capital Expenditure", col)

            results.append({
                "quarter": quarter,
                "revenue": revenue,
                "gross_profit": gross_profit,
                "operating_income": operating_income,
                "net_income": net_income,
                "total_assets": total_assets,
                "total_debt": total_debt,
                "cash": cash,
                "operating_cashflow": operating_cashflow,
                "capital_expenditure": capital_expenditure,
                "gross_margin": _ratio(gross_profit, revenue),
                "operating_margin": _ratio(operating_income, revenue),
                "debt_to_assets": _ratio(total_debt, total_assets),
                "cash_flow_ratio": _ratio(operating_cashflow, net_income),
            })

        return results

    except Exception as e:
        print(f"Error fetching financial ratios for {ticker}: {e}")
        return []


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

    print("\n--- Key Financial Ratios (last 4 quarters) ---")
    ratios = get_key_financial_ratios(ticker)
    print(f"Quarters returned: {len(ratios)}")
    for r in ratios:
        print(f"\n  Quarter: {r['quarter']}")
        for k, v in r.items():
            if k == "quarter":
                continue
            if v is None:
                print(f"    {k:22s} None")
            elif k in ("gross_margin", "operating_margin", "debt_to_assets", "cash_flow_ratio"):
                print(f"    {k:22s} {v:.4f}")
            else:
                print(f"    {k:22s} {v:,.0f}")