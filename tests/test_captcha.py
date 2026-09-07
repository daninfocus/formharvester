"""Tests for the captcha providers and factory (HTTP mocked, no network)."""

from __future__ import annotations

from typing import Any

import pytest

from formharvester.captcha import (
    DeathByCaptchaSolver,
    TwoCaptchaSolver,
    create_solver,
)
from formharvester.captcha import deathbycaptcha as dbc_mod
from formharvester.captcha import twocaptcha as two_mod


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = b"\x89PNG\r\n\x1a\n"

    def json(self) -> dict[str, Any]:
        return self._payload


# --- factory ----------------------------------------------------------------


def test_factory_none_and_auto_detect() -> None:
    assert create_solver(None) is None
    assert create_solver("none") is None
    assert isinstance(create_solver(None, dbc_username="u", dbc_password="p"), DeathByCaptchaSolver)
    assert isinstance(create_solver(None, twocaptcha_api_key="k"), TwoCaptchaSolver)


def test_factory_explicit_providers() -> None:
    assert isinstance(create_solver("2captcha", twocaptcha_api_key="k"), TwoCaptchaSolver)
    assert isinstance(
        create_solver("deathbycaptcha", dbc_username="u", dbc_password="p"),
        DeathByCaptchaSolver,
    )


def test_factory_validates_and_rejects_unknown() -> None:
    with pytest.raises(ValueError):
        create_solver("2captcha")  # missing key
    with pytest.raises(ValueError):
        create_solver("deathbycaptcha", dbc_username="u")  # missing password
    with pytest.raises(ValueError):
        create_solver("captcha-monster")


# --- 2captcha ---------------------------------------------------------------


def test_twocaptcha_solve_image(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: dict[str, Any] = {}

    def fake_post(url: str, data: dict[str, Any], timeout: int) -> FakeResponse:
        posted.update(data)
        return FakeResponse({"status": 1, "request": "42"})

    def fake_get(url: str, params: dict[str, Any], timeout: int) -> FakeResponse:
        return FakeResponse({"status": 1, "request": "SOLVED"})

    monkeypatch.setattr(two_mod.requests, "post", fake_post)
    monkeypatch.setattr(two_mod.requests, "get", fake_get)

    solver = TwoCaptchaSolver("key", poll_interval=0)
    assert solver.solve_image(b"imgbytes") == "SOLVED"
    assert posted["method"] == "base64"
    assert posted["key"] == "key"


def test_twocaptcha_recaptcha_submit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(two_mod.requests, "post", lambda *a, **k: FakeResponse({"status": 0, "request": "ERR"}))
    solver = TwoCaptchaSolver("key", poll_interval=0)
    assert solver.solve_recaptcha("sitekey", "https://x.com") is None


# --- deathbycaptcha ---------------------------------------------------------


def test_deathbycaptcha_solve_recaptcha(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, data: dict[str, Any], headers: dict[str, Any], timeout: int) -> FakeResponse:
        return FakeResponse({"captcha": 7, "text": ""})

    def fake_get(url: str, headers: dict[str, Any], timeout: int) -> FakeResponse:
        return FakeResponse({"captcha": 7, "text": "token-xyz"})

    monkeypatch.setattr(dbc_mod.requests, "post", fake_post)
    monkeypatch.setattr(dbc_mod.requests, "get", fake_get)

    solver = DeathByCaptchaSolver("user", "pass", poll_interval=0)
    assert solver.solve_recaptcha("sitekey", "https://x.com") == "token-xyz"
