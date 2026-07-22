"""Captcha solving providers and browser-side handling."""

from formharvester.captcha.base import CaptchaSolver
from formharvester.captcha.deathbycaptcha import DeathByCaptchaSolver
from formharvester.captcha.detector import CaptchaMixin
from formharvester.captcha.factory import CaptchaProvider, create_solver
from formharvester.captcha.twocaptcha import TwoCaptchaSolver

__all__ = [
    "CaptchaMixin",
    "CaptchaProvider",
    "CaptchaSolver",
    "DeathByCaptchaSolver",
    "TwoCaptchaSolver",
    "create_solver",
]
