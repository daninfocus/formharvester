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
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Literal

from rich.console import Console

from formharvester.captcha import create_solver
from formharvester.captcha.base import CaptchaSolver
from formharvester.core import HarvesterCore
from formharvester.llm import GeneratedFormContent, LlmClient, LlmError, create_llm_client
from formharvester.scraper import GoogleSearchMixin
from formharvester.technology import TechnologyEvidence, TechnologyMatch

__all__ = [
    "FormFillDetails",
    "FormHarvester",
    "CaptchaError",
    "GeneratedFormContent",
    "HarvestResult",
    "HarvestStatus",
    "HarvesterOptions",
    "LlmClient",
    "LlmError",
    "TechnologyEvidence",
    "TechnologyMatch",
    "discover_sites",
    "harvest_site",
    "harvest_sites",
]


class CaptchaError(RuntimeError):
    """The search engine served a captcha and no wait was configured to sit it out."""


# The per-site outcomes the engine can report - the same tokens the CLI writes.
HarvestStatus = Literal[
    "SUBMITTED",
    "FORM_NOT_FOUND",
    "BUTTON_NOT_FOUND",
    "VISITED",
    "LLM_ERROR",
    "REVIEW_SKIPPED",
    "POLICY_BLOCKED",
    "NOT_QUALIFIED",
    "DRY_RUN",
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
    """Engine options (maps to the CLI's saved settings).

    Provide either a ready ``captcha_solver`` or provider credentials
    (``captcha_provider`` + creds), which are turned into a solver for you.
    """

    send_form: bool = True
    headless: bool = True
    max_time: int = 30
    debug: bool = False
    detect_technologies: bool = True
    llm_enabled: bool = False
    llm_client: LlmClient | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_request_timeout: int = 60
    llm_review_before_submit: bool = False
    captcha_solver: CaptchaSolver | None = None
    captcha_provider: str | None = None
    dbc_username: str | None = None
    dbc_password: str | None = None
    twocaptcha_api_key: str | None = None

    skip_ads: bool = False
    start_page: int = 1
    max_pages: int = 3
    min_delay: int = 8
    max_delay: int = 25
    search_timer: int = 0
    captcha_sleep: int = 0
    keywords: list[str] = field(default_factory=list)

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
    technologies: list[TechnologyMatch] = field(default_factory=list)
    generated: GeneratedFormContent | None = None
    llm_error: str | None = None

    @property
    def submitted(self) -> bool:
        return self.status == "SUBMITTED"


class _InMemoryProgress:
    """In-memory stand-ins for the CLI's file-backed progress hooks.

    ``GoogleSearchMixin`` records progress as it walks result pages so the CLI
    can resume an interrupted run. A library ``discover()`` call is a single
    in-process operation with nothing to resume, so these do nothing.

    This must stay last in :class:`FormHarvester`'s bases: the CLI's ``Bot``
    mixes in the real :class:`~formharvester.cli.progress.ProgressMixin`, and
    nothing here may shadow it.
    """

    def log_remaining_pages(self) -> None:
        return None

    def write_progress(self, term_list: Iterable[str], google: bool) -> None:
        return None

    def update_progress(self, term: str, status: str, google: bool) -> None:
        return None

    def get_website_log(self) -> list[str]:
        return []


class FormHarvester(HarvesterCore, GoogleSearchMixin, _InMemoryProgress):
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
        self.detect_technologies = opts.detect_technologies
        self.llm_enabled = opts.llm_enabled or opts.llm_client is not None
        self.llm_client = opts.llm_client
        if self.llm_enabled and self.send_form and self.llm_client is None:
            self.llm_client = create_llm_client(
                opts.llm_provider or "openai",
                opts.llm_api_key or "",
                opts.llm_model or "gpt-5",
                timeout=opts.llm_request_timeout,
            )
        self.review_before_submit = bool(self.llm_enabled and opts.llm_review_before_submit and not self.DEBUG)
        if self.review_before_submit and self.send_form:
            raise ValueError("Manual LLM review is available through the desktop GUI only.")
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
        self.generated_content: GeneratedFormContent | None = None
        self.llm_error: str | None = None

        self.skip_ads = opts.skip_ads
        self.start_page = opts.start_page
        self.max_google_pages = opts.max_pages
        self.MIN_DELAY = opts.min_delay
        self.MAX_DELAY = opts.max_delay
        self.GOOGLE_TIMER = opts.search_timer
        self.CAPTCHA_SLEEP = opts.captcha_sleep
        self.keywords = list(opts.keywords)
        self.google_term: str | None = None
        self.google_query: str | None = None
        self.google_timer: threading.Thread | None = None
        self.current_page: int | None = None
        self.remaining_pages_log: dict[str, list[int]] = defaultdict(list)

        self.create_driver()

    def check_time(self) -> None:
        """Responsive per-site timeout: also exits once ``crawl`` is cleared."""
        start = time.time()
        while self.crawl:
            if time.time() - start >= self.max_time:
                self.crawl = False
                return
            time.sleep(0.5)

    def check_google_captcha(self) -> None:
        """Raise instead of blocking on the CLI's "solve it yourself" prompt.

        The CLI can sit and wait for a human; a library caller cannot. With
        ``captcha_sleep`` set we still fall back to the shared wait-and-
        retry behaviour.
        """
        if self.css('input[type="text"]'):
            return
        if self.CAPTCHA_SLEEP:
            super().check_google_captcha()
            return
        raise CaptchaError(
            "The search engine served a captcha. Set HarvesterOptions.captcha_sleep "
            "to wait it out, or slow down with min_delay/max_delay/search_timer."
        )

    def wait_google_timer(self) -> None:
        """Join the pacing thread without the CLI's detour to a clock page."""
        if self.google_timer:
            self.google_timer.join()
            self.google_timer = None

    def discover(
        self,
        query: str,
        *,
        max_pages: int | None = None,
        start_page: int | None = None,
    ) -> list[str]:
        """Search the web for ``query`` and return the site root URLs it found.

        Results are de-duplicated by root domain and filtered by
        ``HarvesterOptions.keywords`` when any are set. Feed them straight to
        :meth:`harvest_many`.
        """
        if max_pages is not None:
            self.max_google_pages = max_pages
        if start_page is not None:
            self.start_page = start_page

        self.remaining_pages_log = defaultdict(list)
        return list(self.start_process_google([query]) or [])

    def discover_many(self, queries: Iterable[str]) -> list[str]:
        """Run several queries, preserving order and dropping repeats."""
        seen: set[str] = set()
        found: list[str] = []
        for query in queries:
            for url in self.discover(query):
                if url not in seen:
                    seen.add(url)
                    found.append(url)
        return found

    def harvest(self, url: str) -> HarvestResult:
        """Harvest one site: scrape emails and (optionally) submit its form."""
        self.last_status = None
        self.scraped_emails = set()
        self.technologies = []
        self.generated_content = None
        self.llm_error = None
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
        return HarvestResult(
            url=url,
            status=status,
            emails=emails,
            technologies=list(self.technologies),
            generated=self.generated_content,
            llm_error=self.llm_error,
        )

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


def discover_sites(
    queries: str | Iterable[str],
    options: HarvesterOptions | None = None,
) -> list[str]:
    """Convenience one-shot: search for ``queries`` and return the URLs found."""
    if isinstance(queries, str):
        queries = [queries]
    with FormHarvester(FormFillDetails(), options) as harvester:
        return harvester.discover_many(queries)
