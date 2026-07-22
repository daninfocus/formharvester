"""Build a captcha solver from configuration."""

from __future__ import annotations

from typing import Literal

from formharvester.captcha.base import CaptchaSolver
from formharvester.captcha.deathbycaptcha import DeathByCaptchaSolver
from formharvester.captcha.twocaptcha import TwoCaptchaSolver

CaptchaProvider = Literal["deathbycaptcha", "2captcha", "none"]


def create_solver(
    provider: str | None,
    *,
    dbc_username: str | None = None,
    dbc_password: str | None = None,
    twocaptcha_api_key: str | None = None,
) -> CaptchaSolver | None:
    """Return a solver for ``provider``, or ``None`` when captcha solving is off.

    ``provider`` may be omitted; if DBC credentials are present it defaults to
    DeathByCaptcha (backwards compatible with the old ``[captcha]`` config).
    """
    name = (provider or "").strip().lower()

    if not name:
        if dbc_username and dbc_password:
            name = "deathbycaptcha"
        elif twocaptcha_api_key:
            name = "2captcha"
        else:
            return None

    if name in ("none", "off", "disabled"):
        return None
    if name in ("deathbycaptcha", "dbc"):
        if not (dbc_username and dbc_password):
            raise ValueError("deathbycaptcha requires dbc_username and dbc_password")
        return DeathByCaptchaSolver(dbc_username, dbc_password)
    if name in ("2captcha", "twocaptcha"):
        if not twocaptcha_api_key:
            raise ValueError("2captcha requires twocaptcha_api_key")
        return TwoCaptchaSolver(twocaptcha_api_key)

    raise ValueError(f"unknown captcha provider: {provider!r}")
