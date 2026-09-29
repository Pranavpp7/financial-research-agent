"""Unit tests for GROQ_MODEL env resolution and auth-error detection."""
import pytest
from groq import AuthenticationError

from backend.core.groq_config import (
    DEFAULT_GROQ_MODEL,
    get_groq_model,
    is_groq_auth_error,
)


def test_default_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    assert get_groq_model() == DEFAULT_GROQ_MODEL


def test_env_overrides_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_MODEL", "my-custom-groq-model")
    assert get_groq_model() == "my-custom-groq-model"


def test_empty_string_falls_back_to_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_MODEL", "")
    assert get_groq_model() == DEFAULT_GROQ_MODEL


def test_whitespace_only_falls_back_to_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GROQ_MODEL", "   ")
    assert get_groq_model() == DEFAULT_GROQ_MODEL


def test_is_groq_auth_error_authentication_error():
    import httpx

    response = httpx.Response(
        401, request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    )
    exc = AuthenticationError(
        message="Invalid API Key",
        response=response,
        body={"error": {"code": "invalid_api_key"}},
    )
    assert is_groq_auth_error(exc) is True


def test_is_groq_auth_error_message_heuristics():
    assert is_groq_auth_error(
        RuntimeError("Error code: 401 - {'error': {'code': 'invalid_api_key'}}")
    )
    assert is_groq_auth_error(RuntimeError("invalid api key"))
    assert is_groq_auth_error(ValueError("timeout")) is False


def test_is_groq_transient_error_timeout():
    import httpx
    from groq import APITimeoutError

    from backend.core.groq_config import is_groq_transient_error

    exc = APITimeoutError(
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    )
    assert is_groq_transient_error(exc) is True
    assert is_groq_auth_error(exc) is False
