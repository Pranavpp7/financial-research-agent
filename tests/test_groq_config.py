"""Unit tests for GROQ_MODEL env resolution."""
import pytest

from backend.core.groq_config import DEFAULT_GROQ_MODEL, get_groq_model


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
