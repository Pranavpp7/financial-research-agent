"""Celery analysis-task error / retry behavior."""
from unittest.mock import MagicMock, patch

import httpx
import pytest
from celery.exceptions import Retry
from groq import APITimeoutError, AuthenticationError

from backend.tasks.analysis_tasks import run_analysis_task


def _auth_error() -> AuthenticationError:
    response = httpx.Response(
        401,
        request=httpx.Request(
            "POST", "https://api.groq.com/openai/v1/chat/completions"
        ),
    )
    return AuthenticationError(
        message="Invalid API Key",
        response=response,
        body={"error": {"message": "Invalid API Key", "code": "invalid_api_key"}},
    )


def _timeout_error() -> APITimeoutError:
    return APITimeoutError(
        request=httpx.Request(
            "POST", "https://api.groq.com/openai/v1/chat/completions"
        )
    )


@pytest.fixture
def celery_request():
    """Give bind=True tasks a request id so update_state / retry work."""
    run_analysis_task.push_request(id="unit-test-task", retries=0)
    try:
        yield
    finally:
        run_analysis_task.pop_request()


def test_invalid_key_makes_exactly_one_groq_call_and_fails(monkeypatch, celery_request):
    """Auth on supervisor must not fan out to five analyses + synthesis."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_invalid_key_for_unit_tests_xx")

    company = MagicMock(id=1, name="Apple Inc.", ticker="AAPL")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = company

    create = MagicMock(side_effect=_auth_error())
    client = MagicMock()
    client.chat.completions.create = create

    limiter = MagicMock()
    limiter.acquire = MagicMock()

    with (
        patch("backend.agents.run_agent.SessionLocal", return_value=db),
        patch("backend.agents.supervisor.Groq", return_value=client),
        patch("backend.agents.analyzer.Groq", return_value=client),
        patch("backend.agents.synthesizer.Groq", return_value=client),
        patch("backend.agents.supervisor.get_rate_limiter", return_value=limiter),
        patch("backend.agents.analyzer.get_rate_limiter", return_value=limiter),
        patch("backend.agents.synthesizer.get_rate_limiter", return_value=limiter),
        patch.object(run_analysis_task, "update_state", MagicMock()),
        patch.object(run_analysis_task, "retry") as retry_mock,
    ):
        with pytest.raises(AuthenticationError):
            run_analysis_task.run(
                "AAPL", "What is the earnings outlook?", force_refresh=True
            )

    assert create.call_count == 1
    retry_mock.assert_not_called()


def test_supervisor_timeout_triggers_celery_retry(monkeypatch, celery_request):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_invalid_key_for_unit_tests_xx")

    with (
        patch(
            "backend.tasks.analysis_tasks.analyze",
            side_effect=_timeout_error(),
        ),
        patch.object(run_analysis_task, "update_state", MagicMock()),
        patch.object(
            run_analysis_task, "retry", side_effect=Retry()
        ) as retry_mock,
    ):
        with pytest.raises(Retry):
            run_analysis_task.run(
                "AAPL", "What is the earnings outlook?", force_refresh=True
            )

    retry_mock.assert_called_once()
    kwargs = retry_mock.call_args.kwargs
    assert isinstance(kwargs.get("exc"), APITimeoutError)
