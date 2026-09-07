"""Non-billable connectivity checks for configured external services."""

from __future__ import annotations

import requests

from formharvester.settings import CaptchaSettings, LlmSettings

__all__ = ["check_captcha_health", "check_llm_health"]

_TIMEOUT = 5


def _result(name: str, state: str, detail: str) -> dict[str, str]:
    return {"name": name, "state": state, "detail": detail}


def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    json: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    parse_json: bool = True,
) -> tuple[bool, str, dict[str, object] | None]:
    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json,
            data=data,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        if parse_json:
            body = response.json()
            if not isinstance(body, dict):
                return False, "unexpected response", None
            return True, "ready", body
        return True, "ready", None
    except requests.Timeout:
        return False, "timed out", None
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            return False, f"HTTP {response.status_code}", None
        return False, "unreachable", None
    except ValueError:
        return False, "unexpected response", None


def check_llm_health(settings: LlmSettings) -> dict[str, str]:
    """Check provider authentication without sending a generation request."""
    if not settings.enabled:
        return _result("LLM", "disabled", "disabled")

    provider = settings.provider
    api_key = settings.api_key_for_provider().strip()
    if not api_key:
        return _result("LLM", "warning", f"{provider} key not configured")

    endpoints: dict[str, tuple[str, dict[str, str]]] = {
        "openai": (
            "https://api.openai.com/v1/models",
            {"Authorization": f"Bearer {api_key}"},
        ),
        "anthropic": (
            "https://api.anthropic.com/v1/models",
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        ),
        "deepseek": (
            "https://api.deepseek.com/models",
            {"Authorization": f"Bearer {api_key}"},
        ),
    }
    url, headers = endpoints[provider]
    ok, detail, body = _request("GET", url, headers=headers)
    if ok and (body is None or not isinstance(body.get("data"), list)):
        ok, detail = False, "unexpected response"
    return _result("LLM", "ok" if ok else "warning", f"{provider}: {detail}")


def check_captcha_health(settings: CaptchaSettings) -> dict[str, str]:
    """Check configured CAPTCHA credentials without submitting a CAPTCHA."""
    provider = settings.provider.strip().lower()
    if not provider:
        if settings.dbc_username.strip() and settings.dbc_password.strip():
            provider = "deathbycaptcha"
        elif settings.twocaptcha_api_key.strip():
            provider = "2captcha"
        else:
            return _result("CAPTCHA", "disabled", "not configured")
    if provider in {"none", "off", "disabled"}:
        return _result("CAPTCHA", "disabled", "disabled")

    if provider in {"2captcha", "twocaptcha"}:
        api_key = settings.twocaptcha_api_key.strip()
        if not api_key:
            return _result("CAPTCHA", "warning", "2captcha key not configured")
        ok, detail, body = _request(
            "GET",
            "https://2captcha.com/res.php",
            params={"key": api_key, "action": "getbalance", "json": "1"},
        )
        if ok and (body is None or body.get("status") != 1):
            detail = str(body.get("request", "provider rejected request")) if body else "unexpected response"
            ok = False
        return _result("CAPTCHA", "ok" if ok else "warning", f"2captcha: {detail}")

    if provider in {"deathbycaptcha", "dbc"}:
        username = settings.dbc_username.strip()
        password = settings.dbc_password.strip()
        if not username or not password:
            return _result("CAPTCHA", "warning", "DeathByCaptcha credentials not configured")
        ok, detail, _ = _request(
            "POST",
            "http://api.dbcapi.me/api",
            headers={"Accept": "application/json"},
            data={"username": username, "password": password},
        )
        return _result("CAPTCHA", "ok" if ok else "warning", f"DeathByCaptcha: {detail}")

    return _result("CAPTCHA", "warning", f"unknown provider: {provider}")
