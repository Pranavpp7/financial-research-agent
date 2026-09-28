"""Retry helper for Groq chat completions on HTTP 429."""
from __future__ import annotations

import time
from typing import Any

import structlog
from groq import RateLimitError

logger = structlog.get_logger(__name__)


def chat_completion_with_retry(
    client: Any,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs: Any,
) -> Any:
    """
    Call client.chat.completions.create with exponential backoff on 429.

    Retries up to max_retries times after the first failure (4 attempts total
    by default). Non-rate-limit errors are raised immediately.
    """
    attempt = 0
    while True:
        try:
            return client.chat.completions.create(**kwargs)
        except RateLimitError as e:
            if attempt >= max_retries:
                logger.error(
                    "groq_rate_limit_exhausted",
                    attempts=attempt + 1,
                    error=str(e),
                )
                raise
            delay = base_delay * (2**attempt)
            logger.warning(
                "groq_rate_limit_retry",
                attempt=attempt + 1,
                sleep_seconds=delay,
                error=str(e),
            )
            time.sleep(delay)
            attempt += 1
