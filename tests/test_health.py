"""Tests for non-generation external service health checks."""

from __future__ import annotations

import requests

from formharvester.health import check_captcha_health, check_llm_health
from formharvester.settings import CaptchaSettings, LlmSettings


class _Response:
    def __init__(self, body: object | None = None, status_code: int = 200) -> None:
        self.body = body if body is not None else {"data": []}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self) -> object:
        return self.body


def test_llm_health_does_not_call_provider_without_key(monkeypatch) -> None:
    called = False

    def request(*args, **kwargs):
        nonlocal called
        called = True
        return _Response()

    monkeypatch.setattr("formharvester.health.requests.request", request)
    result = check_llm_health(LlmSettings(enabled=True, provider="openai"))
    assert result == {"name": "LLM", "state": "warning", "detail": "openai key not configured"}
    assert called is False


def test_llm_health_checks_selected_provider_endpoint(monkeypatch) -> None:
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response()

    monkeypatch.setattr("formharvester.health.requests.request", request)
    result = check_llm_health(LlmSettings(enabled=True, provider="deepseek", deepseek_api_key="secret"))
    assert result == {"name": "LLM", "state": "ok", "detail": "deepseek: ready"}
    assert calls[0][0:2] == ("GET", "https://api.deepseek.com/models")
    assert calls[0][2]["headers"]["Authorization"] == "Bearer secret"


def test_llm_health_marks_auth_or_network_failure_warning(monkeypatch) -> None:
    def request(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("formharvester.health.requests.request", request)
    result = check_llm_health(LlmSettings(enabled=True, provider="anthropic", anthropic_api_key="secret"))
    assert result["state"] == "warning"
    assert result["detail"] == "anthropic: unreachable"


def test_llm_health_is_disabled_when_generation_is_off(monkeypatch) -> None:
    called = False

    def request(*args, **kwargs):
        nonlocal called
        called = True
        return _Response()

    monkeypatch.setattr("formharvester.health.requests.request", request)
    assert check_llm_health(LlmSettings(provider="openai")) == {
        "name": "LLM",
        "state": "disabled",
        "detail": "disabled",
    }
    assert called is False


def test_captcha_health_supports_auto_disabled_and_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        "formharvester.health.requests.request",
        lambda *args, **kwargs: _Response({"status": 1, "request": "12.34"}),
    )
    assert check_captcha_health(CaptchaSettings()) == {
        "name": "CAPTCHA",
        "state": "disabled",
        "detail": "not configured",
    }
    assert check_captcha_health(CaptchaSettings(provider="none"))["state"] == "disabled"
    result = check_captcha_health(CaptchaSettings(provider="2captcha", twocaptcha_api_key="secret"))
    assert result == {"name": "CAPTCHA", "state": "ok", "detail": "2captcha: ready"}


def test_captcha_health_marks_provider_error_even_with_http_200(monkeypatch) -> None:
    monkeypatch.setattr(
        "formharvester.health.requests.request",
        lambda *args, **kwargs: _Response({"status": 0, "request": "ERROR_KEY_DOES_NOT_EXIST"}),
    )
    result = check_captcha_health(CaptchaSettings(provider="2captcha", twocaptcha_api_key="secret"))
    assert result == {
        "name": "CAPTCHA",
        "state": "warning",
        "detail": "2captcha: ERROR_KEY_DOES_NOT_EXIST",
    }
