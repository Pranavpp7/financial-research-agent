"""Groq LLM model selection from the environment."""
import os

from dotenv import load_dotenv

load_dotenv()

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


def get_groq_model() -> str:
    """Return GROQ_MODEL from the environment, or the project default.

    Empty / whitespace-only values are treated as unset.
    """
    return (os.getenv("GROQ_MODEL") or "").strip() or DEFAULT_GROQ_MODEL
