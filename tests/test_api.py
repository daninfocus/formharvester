"""Browser-free tests for the library API plumbing.

We monkeypatch the browser (``create_driver``) and the engine core
(``process_url``) so these run without Selenium or a real site. They verify the
parts the library API owns: config mapping, status capture, email extraction,
result mapping and timer-thread cleanup.
"""

from __future__ import annotations

import threading
import time

import pytest

import formharvester
from formharvester import FormFillDetails, FormHarvester, HarvesterOptions


@pytest.fixture(autouse=True)
def _no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FormHarvester, "create_driver", lambda self: None)


def test_details_and_options_mapping() -> None:
    fh = FormHarvester(
        FormFillDetails(first_name="Jane", email="jane@x.com", message="Hi"),
        HarvesterOptions(send_form=False, headless=False, max_time=12, debug=True),
    )
    assert fh.details["first_name"] == "Jane"
    assert fh.details["email"] == "jane@x.com"
    assert fh.send_form is False
    assert fh.HEADLESS is False
    assert fh.max_time == 12
    assert fh.DEBUG is True
    assert fh.captcha_solver is None


def test_harvest_captures_status_and_emails(monkeypatch: pytest.MonkeyPatch) -> None:
    fh = FormHarvester(FormFillDetails(email="me@x.com"))

    def fake_process_url(url: str) -> bool:
        fh.scraped_emails.update({("info@acme.com", url), ("info@acme.com", url)})
        fh._set_status(url, "SUBMITTED")
        return True

    monkeypatch.setattr(fh, "process_url", fake_process_url)
    result = fh.harvest("https://acme.com")

    assert result.status == "SUBMITTED"
    assert result.submitted is True
    assert result.emails == ["info@acme.com"]
    assert result.url == "https://acme.com"


def test_harvest_maps_missing_status_to_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fh = FormHarvester(FormFillDetails())
    monkeypatch.setattr(fh, "process_url", lambda url: None)
    result = fh.harvest("https://acme.com")
    assert result.status == "ERROR"
    assert result.submitted is False
    assert result.emails == []


def test_harvest_recovers_from_engine_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    fh = FormHarvester(FormFillDetails())
    monkeypatch.setattr(fh, "restart_driver", lambda: None)

    def boom(url: str) -> bool:
        raise RuntimeError("navigation failed")

    monkeypatch.setattr(fh, "process_url", boom)
    result = fh.harvest("https://acme.com")
    assert result.status == "ERROR"


def test_harvest_joins_timer_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    fh = FormHarvester(FormFillDetails(), HarvesterOptions(max_time=60))

    def process_with_timer(url: str) -> bool:
        t = threading.Thread(target=fh.check_time)
        fh.threads.append(t)
        t.start()
        time.sleep(0.05)
        fh._set_status(url, "VISITED")
        return True

    monkeypatch.setattr(fh, "process_url", process_with_timer)
    result = fh.harvest("https://acme.com")

    assert result.status == "VISITED"
    assert fh.threads == []  # timer thread cleaned up, did not block for 60s


def test_convenience_harvest_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FormHarvester, "close", lambda self: None)
    monkeypatch.setattr(
        FormHarvester,
        "process_url",
        lambda self, url: self._set_status(url, "FORM_NOT_FOUND"),
    )
    result = formharvester.harvest_site("https://acme.com", FormFillDetails())
    assert result.status == "FORM_NOT_FOUND"
