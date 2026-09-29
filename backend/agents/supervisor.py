"""
Supervisor: decides which specialized analyses to run for a given
user question + ticker. One Groq call with JSON mode.

Architecture decision: this is the routing step in our Option-B
single-LLM-with-dynamic-prompts design. NOT a separate agent
instance; just a prompt that produces a route.
"""
import json
import os

import structlog
from dotenv import load_dotenv
from groq import Groq

from backend.core.groq_config import get_groq_model, is_groq_auth_error
from backend.core.rate_limiter import get_rate_limiter

load_dotenv()

logger = structlog.get_logger(__name__)


VALID_ANALYSES = ["earnings", "sec", "news", "risk", "forecast"]


SYSTEM = """\
You are a supervisor that routes a financial-research question to one or
more specialized analyses. The available analyses are:

- "earnings": quarterly EPS history + the earnings_surprise_predictor ML model
- "sec": semantic search over the company's SEC filings (10-K/10-Q)
- "news": recent news articles with FinBERT sentiment scores
- "risk": Beneish M-Score + anomaly detector for accounting/financial risk
- "forecast": Prophet revenue forecast + KMeans peer cluster -- useful for
  growth trajectory and competitive positioning questions

Route "forecast" for questions about revenue growth, future outlook,
competitive position, or peer comparison.

Pick the minimum subset required to answer the question well. Always
include at least one analysis. Respond with ONLY a JSON object of the form
{"analyses": ["earnings", "news"]}.
"""


class Supervisor:
    def __init__(self, model: str | None = None):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set in .env")
        self.client = Groq(api_key=api_key)
        self.model = model or get_groq_model()

    def decide(self, ticker: str, question: str) -> list[str]:
        # Acquire OUTSIDE the try — this was the one Groq call site with no
        # rate limiting at all. Kept out of the except-fallback on purpose:
        # falling back to ALL five analyses on a rate-limit error would make
        # the overload worse; propagating lets the Celery task retry instead.
        get_rate_limiter().acquire("groq")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": (
                        f"Given this question about {ticker}: {question}\n\n"
                        "Which analyses are needed?"
                    )},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content)
            analyses = [a for a in data.get("analyses", []) if a in VALID_ANALYSES]
            if not analyses:
                raise ValueError("supervisor returned no valid analyses")
            logger.info("supervisor_route", ticker=ticker, analyses=analyses)
            return analyses
        except (json.JSONDecodeError, ValueError, TypeError, KeyError) as e:
            # Soft routing failures only: bad/empty JSON or invalid route list.
            logger.warning(
                "supervisor_fallback", ticker=ticker, error=str(e),
                fallback=list(VALID_ANALYSES),
            )
            return list(VALID_ANALYSES)
        except Exception as e:
            # Auth and other hard Groq/client errors must not trigger run-all.
            if is_groq_auth_error(e):
                logger.error("supervisor_auth_failed", ticker=ticker, error=str(e))
            else:
                logger.error("supervisor_failed", ticker=ticker, error=str(e))
            raise
