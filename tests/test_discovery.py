"""Library-side search discovery (``FormHarvester.discover``).

The browser is never started here: these tests drive the real
``GoogleSearchMixin`` logic against a stubbed Selenium surface, so the thing
under test is the page-walking and filtering, not Chrome.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, cast

import pytest

from formharvester.api import (
    CaptchaError,
    FormFillDetails,
    FormHarvester,
    HarvesterOptions,
    _InMemoryProgress,
)
from formharvester.cli.app import Bot
from formharvester.cli.progress import ProgressMixin
from formharvester.utils import filter_scraped_links

RESULTS = {
    1: ["https://acme.com/a", "https://acme.com/b", "https://beta.io/x"],
    2: ["https://gamma.dev/p", "https://acme.com/c"],
}


class _FakeSwitchTo:
    def frame(self, target):
        return None

    def default_content(self):
        return None


class _FakeDriver:
    """Only what the search flow reaches for directly, outside css()/xpath()."""

    switch_to = _FakeSwitchTo()


class _StubHarvester(FormHarvester):
    """FormHarvester with Selenium and pacing stubbed out."""

    def __init__(self, options=None, pages=2):
        self._page = 0
        self._pages = pages
        self.captcha = False
        # Deliberately skips FormHarvester.__init__, which would start Chrome.
        opts = options or HarvesterOptions()
        self.details = FormFillDetails().as_engine_details()
        self.skip_ads = opts.skip_ads
        self.start_page = opts.start_page
        self.max_google_pages = opts.max_pages
        self.MIN_DELAY = opts.min_delay
        self.MAX_DELAY = opts.max_delay
        self.GOOGLE_TIMER = opts.search_timer
        self.CAPTCHA_SLEEP = opts.captcha_sleep
        self.keywords = list(opts.keywords)
        self.google_term = None
        self.google_query = None
        self.google_timer = None
        self.current_page = None
        self.remaining_pages_log = defaultdict(list)
        self.driver = cast("Any", _FakeDriver())

    # --- stubbed Selenium surface (signatures stay open so they remain
    # substitutable for the real SeleniumBot methods) ---
    def get(self, page, *args, **kwargs):
        self._page = 1

    def css(self, selector, *args, **kwargs):
        if selector == 'input[type="text"]':
            return None if self.captcha else "search-box"
        if selector == self.GOOGLE_NEXT:
            return "next" if self._page < self._pages else None
        return None

    def xpath(self, selector, *args, **kwargs):
        return RESULTS.get(self._page, [])

    def click(self, element, *args, **kwargs):
        self._page += 1

    def random_sleep(self, *args, **kwargs):
        return None

    def bot_print(self, message, is_input=False, figlet=False):
        return None


def test_discover_returns_deduplicated_root_urls():
    found = _StubHarvester().discover("roofing austin")

    # three distinct sites across two pages, mapped to root domains
    assert sorted(found) == ["https://acme.com", "https://beta.io", "https://gamma.dev"]


def test_discover_applies_keyword_filter():
    options = HarvesterOptions(keywords=["acme"])
    assert _StubHarvester(options).discover("roofing") == ["https://acme.com"]


def test_no_keywords_keeps_every_result():
    """Empty keywords must mean "no filter", not "drop everything"."""
    assert filter_scraped_links([], ["https://a.com"]) == ["https://a.com"]
    assert _StubHarvester(HarvesterOptions(keywords=[])).discover("x")


def test_discover_many_preserves_order_and_drops_repeats():
    found = _StubHarvester().discover_many(["query one", "query two"])
    assert found == ["https://acme.com", "https://beta.io", "https://gamma.dev"]


def test_captcha_raises_instead_of_blocking():
    bot = _StubHarvester()
    bot.captcha = True
    with pytest.raises(CaptchaError, match="captcha_sleep"):
        bot.discover("roofing")


def test_discover_writes_no_progress_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _StubHarvester().discover("roofing")
    assert list(tmp_path.iterdir()) == []


def test_max_pages_override_limits_the_walk():
    bot = _StubHarvester(pages=5)
    bot.discover("roofing", max_pages=1)
    assert bot.max_google_pages == 1


# --- the CLI must be untouched by all of the above ---------------------


def _owner(cls, name):
    return next(c for c in cls.__mro__ if name in c.__dict__)


def test_cli_still_uses_file_backed_progress():
    assert _InMemoryProgress not in Bot.__mro__
    for hook in ("write_progress", "update_progress", "log_remaining_pages", "get_website_log"):
        assert _owner(Bot, hook) is ProgressMixin


def test_library_uses_in_memory_progress():
    for hook in ("write_progress", "update_progress", "log_remaining_pages", "get_website_log"):
        assert _owner(FormHarvester, hook) is _InMemoryProgress
