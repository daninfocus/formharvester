"""Browser-side captcha handling.

Detects captchas in the page and injects solutions, delegating the actual
solving to a :class:`~formharvester.captcha.base.CaptchaSolver`. Mixed into the
engine so it can use the driver primitives (``css``/``xpath``/``script``).
"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urljoin, urlparse

import requests

from formharvester.captcha.base import CaptchaSolver

if TYPE_CHECKING:
    from formharvester._typing import EngineProtocol as _Base
else:
    _Base = object


class CaptchaMixin(_Base):
    # Set by the composed engine; ``None`` disables captcha solving.
    captcha_solver: CaptchaSolver | None = None

    def check_captcha(self, recaptcha: bool = False, image: bool = False) -> str | None:
        """Return a reCAPTCHA site-key or an image-captcha URL if present."""
        if image:
            src = self.xpath(
                '//img[contains(@class, "captcha") or contains(@src, "captcha")]',
                attr="src",
            )
            if src:
                return urljoin(self.driver.current_url, src)

        if recaptcha:
            site_key = self.css(".g-recaptcha", attr="data-sitekey")
            if site_key:
                return site_key

            site_key = self.xpath('//*[contains(@class, "recaptcha") and @data-sitekey]', attr="data-sitekey")
            if site_key:
                return site_key

            src = self.css(".grecaptcha-logo>iframe", attr="src")
            if not src:
                src = self.xpath('//iframe[contains(@src, "recaptcha") and contains(@src, "k=")]', attr="src")
            if src:
                src = html.unescape(src)
                keys = parse_qs(urlparse(src).query).get("k")
                if keys:
                    return keys[0]
        return None

    def _inject_recaptcha_token(self, token: str) -> None:
        target = self.css("#g-recaptcha-response")
        if not target:
            target = self.xpath('//textarea[contains(@id, "recaptcha") or contains(@name, "captcha")]')
        if target:
            self.script("arguments[0].innerHTML = arguments[1];", target, token)

    def check_solve_captchas(self, recaptcha: bool = False, image: bool = False) -> str | bool | None:
        """Detect and solve a captcha. Returns the text (image) or True (reCAPTCHA)."""
        if self.captcha_solver is None:
            return None

        if recaptcha:
            site_key = self.check_captcha(recaptcha=True)
            if not site_key:
                return None
            token = self.captcha_solver.solve_recaptcha(
                site_key,
                self.driver.current_url,
            )
            if token:
                self._inject_recaptcha_token(token)
                return True
            return None

        if image:
            img_url = self.check_captcha(image=True)
            if not img_url:
                return None
            try:
                image_bytes = requests.get(img_url, timeout=30).content
            except requests.RequestException:
                return None
            return self.captcha_solver.solve_image(image_bytes)

        return None
