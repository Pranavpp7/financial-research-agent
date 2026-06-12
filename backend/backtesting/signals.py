"""
Convert a Report into a tradable signal.

Heuristic v1:
  - signal = "bullish" if confidence > 0.7 AND risk_level != "high"
    AND len(bull_case) > len(bear_case)
  - signal = "bearish" if risk_level == "high" OR confidence < 0.3
    OR len(bear_case) > 2 * len(bull_case)
  - signal = "neutral" otherwise

This is deliberately simple. A real strategy would use the agent's
bull/bear ratio plus ML prediction confidence, not this coarse proxy.
"""
from typing import Literal

from backend.db.models import Report

Signal = Literal["bullish", "bearish", "neutral"]


def report_to_signal(report: Report) -> Signal:
    conf = report.confidence_score or 0.0
    risk = (report.risk_level or "").lower()
    bull_len = len(report.bull_case or "")
    bear_len = len(report.bear_case or "")

    if conf > 0.7 and risk != "high" and bull_len > bear_len:
        return "bullish"
    if risk == "high" or conf < 0.3 or bear_len > 2 * bull_len:
        return "bearish"
    return "neutral"
