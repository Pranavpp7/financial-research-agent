import yfinance as yf

# Test with Apple — one of the most reliable tickers
ticker = yf.Ticker("AAPL")

# Get basic company info
info = ticker.info
print("Company:", info.get("longName"))
print("Sector:", info.get("sector"))
print("Market Cap:", info.get("marketCap"))

# Get last 4 quarters of earnings
print("\n--- Quarterly Earnings ---")
earnings = ticker.quarterly_income_stmt
print(earnings.head())