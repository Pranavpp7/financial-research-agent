"""
Hand-crafted benchmark questions for AAPL.

Each entry: question, ticker, and expected_themes (used as a sanity-check
hint for human review of the answer; not fed to Ragas as ground truth).

If we ever want a real ground_truth field for Ragas reference-based
metrics, this is where it would live -- write the canonical short answer
for each question.
"""

QUESTIONS = [
    {
        "question": "What are Apple's main revenue streams?",
        "ticker": "AAPL",
        "expected_themes": ["iPhone", "services", "Mac", "wearables", "iPad"],
    },
    {
        "question": "What risk factors does Apple disclose in its most recent 10-Q?",
        "ticker": "AAPL",
        "expected_themes": [
            "supply chain", "competition", "regulation", "data privacy",
            "macro", "concentration",
        ],
    },
    {
        "question": "Did Apple beat earnings estimates last quarter?",
        "ticker": "AAPL",
        "expected_themes": ["EPS", "estimate", "actual", "surprise"],
    },
    {
        "question": "What does Apple say about supply chain concentration?",
        "ticker": "AAPL",
        "expected_themes": ["China", "manufacturing", "single source", "suppliers"],
    },
    {
        "question": "How is Apple's Services segment performing?",
        "ticker": "AAPL",
        "expected_themes": ["growth", "subscription", "App Store", "gross margin"],
    },
    {
        "question": "What artificial intelligence risks does Apple flag?",
        "ticker": "AAPL",
        "expected_themes": [
            "AI", "intellectual property", "data privacy", "cybersecurity",
            "competition",
        ],
    },
    {
        "question": "What is Apple's exposure to litigation or regulatory action?",
        "ticker": "AAPL",
        "expected_themes": [
            "antitrust", "App Store", "regulation", "lawsuit", "EU",
        ],
    },
    {
        "question": "Is there evidence Apple is manipulating earnings?",
        "ticker": "AAPL",
        "expected_themes": [
            "Beneish", "M-Score", "accruals", "manipulator", "clean",
        ],
    },
    {
        "question": "How does the news sentiment for Apple skew recently?",
        "ticker": "AAPL",
        "expected_themes": [
            "positive", "negative", "neutral", "average sentiment",
            "headlines",
        ],
    },
    {
        "question": "What forward-looking statements does Apple make about future growth?",
        "ticker": "AAPL",
        "expected_themes": [
            "guidance", "expectations", "future", "investments", "growth",
        ],
    },
]
