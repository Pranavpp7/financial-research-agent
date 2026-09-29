"""Groq LLM model selection from the environment."""
import os
from typing import Any

from dotenv import load_dotenv
from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    RateLimitError,
)

load_dotenv()

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


def get_groq_model() -> str:
    """Return GROQ_MODEL from the environment, or the project default.

    Empty / whitespace-only values are treated as unset.
    """
    return (os.getenv("GROQ_MODEL") or "").strip() or DEFAULT_GROQ_MODEL


def is_groq_auth_error(exc: BaseException | Any) -> bool:
    """True for Groq authentication / invalid-API-key failures."""
    if isinstance(exc, AuthenticationError):
        return True
    if isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) == 401:
        return True
    msg = str(exc).lower()
    return "invalid_api_key" in msg or "invalid api key" in msg


def is_groq_transient_error(exc: BaseException | Any) -> bool:
    """True for timeouts, connection errors, 5xx, and Groq API rate limits."""
    if isinstance(
        exc,
        (APITimeoutError, APIConnectionError, InternalServerError, RateLimitError),
    ):
        return True
    if isinstance(exc, APIStatusError):
        code = getattr(exc, "status_code", None)
        return isinstance(code, int) and code >= 500
    return False
