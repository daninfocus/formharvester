"""Captcha solver interface.

A solver knows how to turn a captcha challenge into the text/token a form
expects. Implementations talk to a third-party solving service over HTTP. The
engine depends only on this protocol, so providers are swappable and testable.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CaptchaSolver(Protocol):
    def solve_image(self, image: bytes) -> str | None:
        """Solve an image captcha, returning the text or ``None`` on failure."""
        ...

    def solve_recaptcha(self, site_key: str, page_url: str) -> str | None:
        """Solve a reCAPTCHA v2, returning the response token or ``None``."""
        ...
