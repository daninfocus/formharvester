"""Network-free tests for the GUI update check and external links."""

from __future__ import annotations

import requests

from formharvester.core import __VERSION__
from formharvester.gui import api as gui_api
from formharvester.gui.api import Api


class _FakeResponse:
    def __init__(self, payload: dict[str, str] | None = None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> dict[str, str]:
        return self._payload or {}


def test_check_for_updates_reports_newer_release(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    api = Api()
    monkeypatch.setattr(
        gui_api.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse(
            payload={
                "tag_name": "v9.9.9",
                "html_url": "https://github.com/dariomory/formharvester/releases/tag/v9.9.9",
            }
        ),
    )
    result = api.check_for_updates()
    assert result["ok"] is True
    assert result["latest"] == "9.9.9"
    assert result["update_available"] is True
    assert result["url"].endswith("v9.9.9")


def test_check_for_updates_up_to_date(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    api = Api()
    monkeypatch.setattr(
        gui_api.requests,
        "get",
        lambda *args, **kwargs: _FakeResponse(
            payload={
                "tag_name": f"v{__VERSION__}",
                "html_url": "https://github.com/dariomory/formharvester/releases/latest",
            }
        ),
    )
    result = api.check_for_updates()
    assert result["ok"] is True
    assert result["latest"] == __VERSION__
    assert result["update_available"] is False


def test_check_for_updates_network_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    api = Api()

    def _refuse(*args, **kwargs) -> _FakeResponse:
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(gui_api.requests, "get", _refuse)
    result = api.check_for_updates()
    assert result["ok"] is False
    assert "error" in result


def test_open_external_rejects_non_http(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FORMHARVESTER_HOME", str(tmp_path))
    api = Api()
    opened: list[str] = []
    monkeypatch.setattr(gui_api.webbrowser, "open", opened.append)

    result = api.open_external("file:///etc/passwd")
    assert result["ok"] is False
    assert opened == []

    result = api.open_external("https://formharvester.com")
    assert result["ok"] is True
    assert opened == ["https://formharvester.com"]
