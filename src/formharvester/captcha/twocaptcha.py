"""2captcha solver via its HTTP API.

Docs: https://2captcha.com/2captcha-api
"""

from __future__ import annotations

import base64

import requests

from formharvester.captcha._poll import poll_until

_IN = "http://2captcha.com/in.php"
_RES = "http://2captcha.com/res.php"


class TwoCaptchaSolver:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 120.0,
        poll_interval: float = 5.0,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._poll_interval = poll_interval

    def _submit(self, data: dict[str, str]) -> str | None:
        payload = {"key": self._api_key, "json": "1", **data}
        response = requests.post(_IN, data=payload, timeout=30)
        if response.status_code != 200:
            return None
        body = response.json()
        return str(body["request"]) if body.get("status") == 1 else None

    def _poll(self, captcha_id: str) -> str | None:
        def fetch() -> str | None:
            response = requests.get(
                _RES,
                params={"key": self._api_key, "action": "get", "id": captcha_id, "json": "1"},
                timeout=30,
            )
            if response.status_code != 200:
                return None
            body = response.json()
            return str(body["request"]) if body.get("status") == 1 else None

        return poll_until(fetch, timeout=self._timeout, interval=self._poll_interval)

    def solve_image(self, image: bytes) -> str | None:
        encoded = base64.b64encode(image).decode("ascii")
        captcha_id = self._submit({"method": "base64", "body": encoded})
        return self._poll(captcha_id) if captcha_id else None

    def solve_recaptcha(self, site_key: str, page_url: str) -> str | None:
        captcha_id = self._submit(
            {"method": "userrecaptcha", "googlekey": site_key, "pageurl": page_url}
        )
        return self._poll(captcha_id) if captcha_id else None
