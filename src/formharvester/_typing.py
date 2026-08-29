"""Shared typing-only contract for the mixin composition.

Each engine mixin (``captcha``, ``form_handler``, ``scraper``, ``cli``) is
written assuming it will be mixed into :class:`~formharvester.core.HarvesterCore`
alongside its siblings - that composition is real at runtime (see
``core.HarvesterCore``, ``cli.app.Bot``, ``api.FormHarvester``). But a type
checker verifying one mixin's method bodies in isolation has no way to know
its siblings exist, since it resolves attributes against the class where the
method is *defined*, not the eventual composed subclass.

This Protocol describes that full composed surface so mixins can declare it as
a type-checking-only base (see the ``if TYPE_CHECKING`` pattern used in each
mixin module) without affecting the real runtime MRO.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Protocol

from selenium import webdriver

from formharvester.captcha.base import CaptchaSolver
from formharvester.llm import GeneratedFormContent, LlmClient, ReviewCallback
from formharvester.technology import TechnologyMatch


class EngineProtocol(Protocol):
    # --- browser + engine state (engine.SeleniumBot / core.HarvesterCore) --
    driver: webdriver.Chrome
    c: Any
    captcha_solver: CaptchaSolver | None
    crawl: bool
    max_time: int
    threads: list[threading.Thread]
    HEADLESS: bool | None
    DEV_SETTINGS: bool | None
    DEBUG: bool
    log_dir: str

    # --- output locations (cli.app.Bot.__init__) ---------------------------
    data_dir: Path

    # --- form-fill / harvest state (Bot.__init__ / FormHarvester.__init__) -
    details: dict[str, str]
    send_form: bool
    name_filled: bool
    visited_links: list[str]
    scraped_emails: set[tuple[str, str]]
    visited_websites: list[str]
    technologies: list[TechnologyMatch]
    detect_technologies: bool
    llm_enabled: bool
    llm_client: LlmClient | None
    review_before_submit: bool
    review_callback: ReviewCallback | None
    generated_content: GeneratedFormContent | None
    llm_error: str | None

    # --- CLI-only config (cli.app.Bot.__init__) ----------------------------
    mode: str
    keywords: list[str]
    google_queries: list[str]
    skip_ads: bool
    start_page: int
    max_google_pages: int
    MIN_DELAY: int
    MAX_DELAY: int
    CAPTCHA_SLEEP: int
    GOOGLE_TIMER: int
    generate_email_sources: bool
    google_term: str | None
    google_query: str | None
    google_timer: threading.Thread | None
    current_page: int | None
    remaining_pages_log: dict[str, list[int]]

    # --- SeleniumBot primitives ---------------------------------------------
    def css(self, selector, node=None, getall=False, attr=None, wait=None, wait_for=None): ...
    def xpath(self, selector, node=None, getall=False, attr=None, wait=None): ...
    def script(self, script, *args): ...
    def get(self, page, pre_sleep=0, sleep=0, timeout=False, check=False): ...
    def click(self, element, wait=False, css=False, xpath=False, js_click=False, sleep=False, double=False): ...
    def write(
        self,
        field,
        text,
        css=False,
        xpath=False,
        name=False,
        wait=False,
        clear=False,
        human=False,
        submit=False,
    ): ...
    def press_key(self, key) -> None: ...
    def wait_show_element(self, selector, xpath=False, wait=99999): ...
    def random_sleep(self, *args, **kwargs) -> None: ...
    def highlight(self, element, css=False) -> None: ...
    def create_driver(self) -> None: ...
    def restart_driver(self) -> None: ...

    # --- cross-mixin methods -------------------------------------------------
    def bot_print(self, message, is_input=False, figlet=False) -> None: ...
    def check_time(self) -> None: ...
    def check_solve_captchas(self, recaptcha=False, image=False): ...
    def scrape_emails(self) -> None: ...
    def _set_status(self, url: str, status: str) -> None: ...
    def _note_visited(self, url: str) -> None: ...
    def _scan_technologies(self) -> list[TechnologyMatch]: ...
    def get_website_log(self) -> list[str]: ...
    def export_technologies(self, url: str, filename: str | None = None) -> None: ...
    def log_remaining_pages(self) -> None: ...
    def write_progress(self, term_list, google) -> None: ...
    def update_progress(self, term, status, google) -> None: ...
