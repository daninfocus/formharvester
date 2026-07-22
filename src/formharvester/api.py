"""Programmatic API for FormHarvester.

The library entry point. Reuses the shared :class:`HarvesterCore` engine
(Selenium navigation, email scraping, contact-form handling) without the CLI's
config/file coupling: pass form-fill details and options in code and get
structured :class:`HarvestResult` objects back.

    from formharvester import FormHarvester, FormFillDetails

    with FormHarvester(FormFillDetails(email="me@example.com", message="Hi")) as fh:
        result = fh.harvest("https://acme.com")
        print(result.status, result.emails, result.submitted)
"""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Literal

from rich.console import Console

from formharvester.captcha import create_solver
from formharvester.captcha.base import CaptchaSolver
from formharvester.core import HarvesterCore

__all__ = [
    "FormFillDetails",
    "FormHarvester",
    "HarvestResult",
    "HarvestStatus",
    "HarvesterOptions",
    "harvest_site",
    "harvest_sites",
]

# The per-site outcomes the engine can report - the same tokens the CLI writes.
HarvestStatus = Literal[
    "SUBMITTED",
    "FORM_NOT_FOUND",
    "BUTTON_NOT_FOUND",
    "VISITED",
    "ERROR",
]


@dataclass
class FormFillDetails:
    """Values used to fill contact forms (maps to the CLI's input CSV row)."""

    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    email: str = ""
    location: str = ""
    city: str = ""
    state: str = ""
    subject: str = ""
    message: str = ""

    def as_engine_details(self) -> dict[str, str]:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "phone": self.phone,
            "email": self.email,
            "location": self.location,
            "city": self.city,
            "state": self.state,
            "subject": self.subject,
            "message": self.message,
        }


@dataclass
class HarvesterOptions:
    """Engine options (maps to the CLI's ``config.txt`` settings).

    Provide either a ready ``captcha_solver`` or provider credentials
    (``captcha_provider`` + creds), which are turned into a solver for you.
    """

    send_form: bool = True
    headless: bool = True
    max_time: int = 30
    debug: bool = False
    captcha_solver: CaptchaSolver | None = None
    captcha_provider: str | None = None
    dbc_username: str | None = None
    dbc_password: str | None = None
    twocaptcha_api_key: str | None = None

    def resolve_solver(self) -> CaptchaSolver | None:
        if self.captcha_solver is not None:
            return self.captcha_solver
        return create_solver(
            self.captcha_provider,
            dbc_username=self.dbc_username,
            dbc_password=self.dbc_password,
            twocaptcha_api_key=self.twocaptcha_api_key,
        )


@dataclass
class HarvestResult:
    """Structured outcome for one harvested site."""

    url: str
    status: HarvestStatus
    emails: list[str] = field(default_factory=list)

    @property
    def submitted(self) -> bool:
        return self.status == "SUBMITTED"


class FormHarvester(HarvesterCore):
    """Library-friendly driver over the shared engine.

    Constructs without reading any files, manages the browser lifecycle, and
    returns :class:`HarvestResult` objects. Use as a context manager so the
    browser is always closed.
    """

    def __init__(
        self,
        details: FormFillDetails,
        options: HarvesterOptions | None = None,
    ) -> None:
        opts = options or HarvesterOptions()
        self.c = Console()

        self.details = details.as_engine_details()

        self.send_form = opts.send_form
        self.DEBUG = opts.debug
        self.max_time = opts.max_time
        self.HEADLESS = opts.headless
        self.DEV_SETTINGS = False
        self.captcha_solver = opts.resolve_solver()

        self.visited_websites: list[str] = []
        self.visited_links: list[str] = []
        self.scraped_emails: set[tuple[str, str]] = set()
        self.name_filled = False
        self.crawl = True
        self.threads: list[threading.Thread] = []
        self.last_status: str | None = None

        self.create_driver()

    def check_time(self) -> None:
        """Responsive per-site timeout: also exits once ``crawl`` is cleared."""
        start = time.time()
        while self.crawl:
            if time.time() - start >= self.max_time:
                self.crawl = False
                return
            time.sleep(0.5)

    def harvest(self, url: str) -> HarvestResult:
        """Harvest one site: scrape emails and (optionally) submit its form."""
        self.last_status = None
        self.scraped_emails = set()
        self.visited_links = []
        self.name_filled = False
        self.crawl = True

        try:
            self.process_url(url)
        except Exception:
            traceback.print_exc()
            self.last_status = "ERROR"
            self.restart_driver()
        finally:
            self.crawl = False
            while self.threads:
                thread = self.threads.pop()
                thread.join(timeout=2)
            self.crawl = True

        status: HarvestStatus = self.last_status or "ERROR"  # type: ignore[assignment]
        emails = sorted({email for (email, _url) in self.scraped_emails})
        return HarvestResult(url=url, status=status, emails=emails)

    def harvest_many(self, urls: Iterable[str]) -> Iterator[HarvestResult]:
        for url in urls:
            yield self.harvest(url)

    def close(self) -> None:
        try:
            self.driver.quit()
        except Exception:
            pass

    def __enter__(self) -> FormHarvester:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def harvest_site(
    url: str,
    details: FormFillDetails,
    options: HarvesterOptions | None = None,
) -> HarvestResult:
    """Convenience one-shot: harvest a single URL and close the browser."""
    with FormHarvester(details, options) as harvester:
        return harvester.harvest(url)


def harvest_sites(
    urls: Iterable[str],
    details: FormFillDetails,
    options: HarvesterOptions | None = None,
) -> list[HarvestResult]:
    """Convenience: harvest many URLs with one browser session."""
    with FormHarvester(details, options) as harvester:
        return list(harvester.harvest_many(urls))
