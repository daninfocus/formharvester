"""DeathByCaptcha solver via the public HTTP API.

Replaces the old vendored socket client (``dbc_api_python3``). Docs:
https://deathbycaptcha.com/api/http
"""

from __future__ import annotations

import base64
import json

import requests

from formharvester.captcha._poll import poll_until

_BASE = "http://api.dbcapi.me/api"
_HEADERS = {"Accept": "application/json"}


class DeathByCaptchaSolver:
    def __init__(
        self,
        username: str,
        password: str,
        *,
        timeout: float = 120.0,
        poll_interval: float = 5.0,
    ) -> None:
        self._username = username
        self._password = password
        self._timeout = timeout
        self._poll_interval = poll_interval

    def _credentials(self) -> dict[str, str]:
        return {"username": self._username, "password": self._password}

    def _submit(self, data: dict[str, str]) -> int | None:
        response = requests.post(f"{_BASE}/captcha", data=data, headers=_HEADERS, timeout=30)
        if response.status_code not in (200, 303):
            return None
        payload = response.json()
        captcha_id = payload.get("captcha")
        return int(captcha_id) if captcha_id else None

    def _poll(self, captcha_id: int) -> str | None:
        def fetch() -> str | None:
            response = requests.get(f"{_BASE}/captcha/{captcha_id}", headers=_HEADERS, timeout=30)
            if response.status_code != 200:
                return None
            return response.json().get("text") or None

        return poll_until(fetch, timeout=self._timeout, interval=self._poll_interval)

    def solve_image(self, image: bytes) -> str | None:
        encoded = base64.b64encode(image).decode("ascii")
        data = {**self._credentials(), "captchafile": f"base64:{encoded}"}
        captcha_id = self._submit(data)
        return self._poll(captcha_id) if captcha_id else None

    def solve_recaptcha(self, site_key: str, page_url: str) -> str | None:
        data = {
            **self._credentials(),
            "type": "4",
            "token_params": json.dumps({"googlekey": site_key, "pageurl": page_url}),
        }
        captcha_id = self._submit(data)
        return self._poll(captcha_id) if captcha_id else None
