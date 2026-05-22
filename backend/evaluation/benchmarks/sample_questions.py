"""
Hand-crafted benchmark questions for the Ragas baseline.

Each entry:
  question       -- the prompt sent to the agent
  ticker         -- must be a ticker present in the batch-ingestion seed list
                    (NVDA, AAPL, META, JPM, ...). Tickers that aren't ingested
                    + embedded yet are skipped at eval time.
  expected_themes-- sanity-check hints for human review (NOT fed to Ragas)
  ground_truth   -- optional reference answer for reference-based metrics
                    (context_recall). Empty string => those metrics skipped.

The set spans the analytical surface area of the platform: earnings beats,
SEC risk factors, revenue trends, anomaly flags, news sentiment, M-Score
interpretation, bull/bear balance, forward guidance, peer comparison, and a
broad comprehensive-analysis question.
"""

QUESTIONS = [
    # 1. earnings beats
    {
        "question": "Has NVDA been beating consensus EPS estimates in recent quarters?",
        "ticker": "NVDA",
        "expected_themes": ["EPS", "estimate", "actual", "surprise", "beat"],
        "ground_truth": "",
    },
    # 2. SEC risk factors
    {
        "question": "What are the principal risk factors Apple discloses in its most recent 10-K?",
        "ticker": "AAPL",
        "expected_themes": [
            "supply chain", "competition", "regulation", "data privacy",
            "macro", "concentration",
        ],
        "ground_truth": "",
    },
    # 3. revenue trends
    {
        "question": "How has Meta's quarterly revenue trended over the past several quarters?",
        "ticker": "META",
        "expected_themes": ["revenue", "growth", "trend", "quarter"],
        "ground_truth": "",
    },
    # 4. anomaly flags
    {
        "question": "Are there any financial anomalies flagged for JPMorgan's recent results?",
        "ticker": "JPM",
        "expected_themes": ["anomaly", "outlier", "z-score", "flagged", "clean"],
        "ground_truth": "",
    },
    # 5. news sentiment
    {
        "question": "How does recent news sentiment for Apple skew, and what is driving it?",
        "ticker": "AAPL",
        "expected_themes": [
            "positive", "negative", "neutral", "average sentiment", "headlines",
        ],
        "ground_truth": "",
    },
    # 6. M-Score interpretation
    {
        "question": "Does NVDA's Beneish M-Score suggest any earnings-manipulation risk?",
        "ticker": "NVDA",
        "expected_themes": [
            "Beneish", "M-Score", "accruals", "manipulator", "grey", "clean",
        ],
        "ground_truth": "",
    },
    # 7. bull/bear balance
    {
        "question": "Give a balanced bull and bear case for Meta as an investment.",
        "ticker": "META",
        "expected_themes": ["bull", "bear", "upside", "downside", "risk"],
        "ground_truth": "",
    },
    # 8. forward guidance
    {
        "question": "What forward-looking statements does Apple make about future growth?",
        "ticker": "AAPL",
        "expected_themes": [
            "guidance", "expectations", "future", "investments", "growth",
        ],
        "ground_truth": "",
    },
    # 9. peer comparison
    {
        "question": "How does JPMorgan compare to its financial-sector peers?",
        "ticker": "JPM",
        "expected_themes": ["peer", "cluster", "similar", "comparison", "sector"],
        "ground_truth": "",
    },
    # 10. comprehensive analysis
    {
        "question": "Give me a comprehensive investment analysis of NVDA.",
        "ticker": "NVDA",
        "expected_themes": [
            "earnings", "risk", "sentiment", "revenue", "bull", "bear",
        ],
        "ground_truth": "",
    },
    # 11. SEC supply-chain risk (extra coverage)
    {
        "question": "What does Apple say about supply chain concentration and single-source suppliers?",
        "ticker": "AAPL",
        "expected_themes": ["China", "manufacturing", "single source", "suppliers"],
        "ground_truth": "",
    },
    # 12. news catalysts (extra coverage)
    {
        "question": "What are the key positive and negative news catalysts for Meta recently?",
        "ticker": "META",
        "expected_themes": ["catalyst", "lawsuit", "product", "downgrade", "beat"],
        "ground_truth": "",
    },
]
